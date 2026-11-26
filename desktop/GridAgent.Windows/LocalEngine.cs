using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;

namespace GridAgent.Windows;

internal sealed record EngineSettings(string Python, string Workspace, string Model, string BaseUrl, string ApiKey);

internal static class LocalEngine
{
    public static async Task RunAsync(EngineSettings settings, object request, Action<JsonElement> receive)
    {
        var start = new ProcessStartInfo
        {
            FileName = settings.Python,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false),
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8
        };
        foreach (var arg in new[] { "-X", "utf8", "-m", "gridagent.desktop_bridge", "--workspace", settings.Workspace })
            start.ArgumentList.Add(arg);
        start.Environment.Remove("PYTHONHOME");
        start.Environment.Remove("PYTHONPATH");
        start.Environment["PYTHONUTF8"] = "1";
        start.Environment["PYTHONNOUSERSITE"] = "1";
        if (!string.IsNullOrWhiteSpace(settings.Model)) start.Environment["GRIDAGENT_MODEL"] = settings.Model;
        if (!string.IsNullOrWhiteSpace(settings.BaseUrl)) start.Environment["GRIDAGENT_BASE_URL"] = settings.BaseUrl;
        if (!string.IsNullOrWhiteSpace(settings.ApiKey)) start.Environment["GRIDAGENT_API_KEY"] = settings.ApiKey;
        using var process = Process.Start(start) ?? throw new InvalidOperationException("Could not start local engine.");
        // Drain diagnostics without exposing provider responses or secrets in the transcript.
        var drain = process.StandardError.BaseStream.CopyToAsync(Stream.Null);
        try
        {
            await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(request));
            process.StandardInput.Close();
            bool done = false;
            string? line;
            while ((line = await process.StandardOutput.ReadLineAsync()) is not null)
            {
                using var doc = JsonDocument.Parse(line);
                var evt = doc.RootElement;
                done |= evt.GetProperty("kind").GetString() == "done";
                receive(evt);
            }
            await process.WaitForExitAsync();
            await drain;
            if (process.ExitCode != 0 || !done)
                throw new InvalidOperationException("Local engine did not complete.");
        }
        finally
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                await process.WaitForExitAsync();
            }
        }
    }
}
