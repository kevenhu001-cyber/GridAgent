using System.IO;
using System.Text.Json;

namespace GridAgent.Windows;

// Explicit, fixed offline/optional-plugin smoke activation for development MSIX only.
// No arbitrary arguments, user workspaces, provider credentials or script execution.
internal static class MsixSmoke
{
    public static async Task RunAsync()
    {
        var marker = Path.Combine(AppDataPaths.DataRoot, "msix-smoke.json");
        var root = Path.Combine(AppDataPaths.DataRoot, "msix-smoke-" + Guid.NewGuid().ToString("N"));
        string stage = "initialize";
        bool success = false;
        string? error = null;
        string? oldPlugins = Environment.GetEnvironmentVariable("GRIDAGENT_PLUGIN_ROOT");
        try
        {
            Directory.CreateDirectory(root);
            Environment.SetEnvironmentVariable("GRIDAGENT_PLUGIN_ROOT", Path.Combine(root, "plugins"));
            var settings = new EngineSettings(Path.Combine(AppContext.BaseDirectory, "runtime", "python.exe"), root, "", "", "");
            using var engine = new DesktopEngineClient();
            async Task<List<JsonElement>> Request(object request)
            {
                var events = new List<JsonElement>();
                await engine.RunAsync(settings, request, e => events.Add(e.Clone()));
                if (events.Any(e => e.GetProperty("kind").GetString() == "error"))
                    throw new InvalidOperationException("Bridge reported an error.");
                return events;
            }
            var first = await Request(new { action = "initialize" });
            if (!first.Any(e => e.GetProperty("kind").GetString() == "sessions"))
                throw new InvalidOperationException("Missing workspace metadata.");
            var second = await Request(new { action = "refresh" });
            if (!second.Any(e => e.GetProperty("kind").GetString() == "runs"))
                throw new InvalidOperationException("Missing workspace index.");
            stage = "native-solver";
            var input = Path.Combine(root, "smoke-program.json");
            await File.WriteAllTextAsync(input, """{"backend":"pandapower","base":"case14"}""");
            var runEvents = await Request(new { action = "local", command = "native-program", args = new[] { input } });
            var raw = runEvents.First(e => e.GetProperty("kind").GetString() == "result").GetProperty("data").GetString();
            using var result = JsonDocument.Parse(raw!);
            if (result.RootElement.GetProperty("status").GetString() != "ok" ||
                !result.RootElement.GetProperty("quality").GetProperty("passed").GetBoolean())
                throw new InvalidOperationException("Native AC solver or independent checks failed.");
            stage = "plugin-install";
            // Only the isolated smoke plugin directory is affected.
            await Request(new { action = "local", command = "plugin-install", args = new[] { "rainflow" } });
            async Task<bool> Installed()
            {
                var catalog = (await Request(new { action = "plugins" })).First(e => e.GetProperty("kind").GetString() == "plugins");
                return catalog.GetProperty("data").EnumerateArray().Any(p =>
                    p.GetProperty("id").GetString() == "rainflow" && p.GetProperty("installed").GetBoolean() && p.GetProperty("managed").GetBoolean());
            }
            if (!await Installed()) throw new InvalidOperationException("Managed plugin did not install.");
            stage = "plugin-remove";
            await Request(new { action = "local", command = "plugin-remove", args = new[] { "rainflow" } });
            if (await Installed()) throw new InvalidOperationException("Managed plugin was not removed.");
            success = true;
            stage = "complete";
        }
        catch (Exception ex) { error = ex.GetType().Name; }
        finally
        {
            Environment.SetEnvironmentVariable("GRIDAGENT_PLUGIN_ROOT", oldPlugins);
            try { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            var temp = marker + ".tmp";
            await File.WriteAllTextAsync(temp, JsonSerializer.Serialize(new { success, stage, error }));
            File.Move(temp, marker, overwrite: true);
        }
    }
}
