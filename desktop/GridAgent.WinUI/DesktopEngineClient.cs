using System.Diagnostics;
using System.IO;
using System.Text.Json;

namespace GridAgent.Windows;

// Separate bounded read lane and isolated mutation lane. Never replay a mutation.
internal sealed class DesktopEngineClient : IDisposable
{
    private static readonly HashSet<string> ReadActions = new(StringComparer.Ordinal)
    { "initialize", "refresh", "history", "waveform", "analysis-charts", "waveform-overlay", "topology", "artifact-preview" };
    private readonly SemaphoreSlim _gate = new(1, 1);
    private Process? _reader;
    private Task? _drain;
    private EngineSettings? _identity;
    private int _requests;
    private bool _disposed;

    public async Task RunAsync(EngineSettings settings, object request, Action<JsonElement> receive)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        var body = JsonSerializer.SerializeToElement(request);
        var action = body.GetProperty("action").GetString() ?? "";
        if (!ReadActions.Contains(action))
        {
            await LocalEngine.RunAsync(settings, request, receive);
            return;
        }
        await _gate.WaitAsync();
        try
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            // Do not persist credentials in the resident process or its identity.
            var identity = settings with { ApiKey = "" };
            if (_reader == null || _reader.HasExited || _identity != identity || _requests >= 64)
            {
                CloseReader();
                _reader = Process.Start(LocalEngine.CreateStartInfo(identity, readService: true))
                    ?? throw new InvalidOperationException("Could not start metadata service.");
                _drain = _reader.StandardError.BaseStream.CopyToAsync(Stream.Null);
                _identity = identity;
            }
            var id = Guid.NewGuid().ToString("N");
            var frame = JsonSerializer.Serialize(new { version = 1, id, request = body });
            if (frame.Length > 65535) throw new InvalidOperationException("Read request too large.");
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(120));
            await _reader.StandardInput.WriteLineAsync(frame.AsMemory(), timeout.Token);
            await _reader.StandardInput.FlushAsync(timeout.Token);
            while (true)
            {
                var line = await _reader.StandardOutput.ReadLineAsync(timeout.Token);
                if (line == null || line.Length > 16 * 1024 * 1024)
                    throw new InvalidOperationException("Metadata service closed or exceeded frame limit.");
                using var document = JsonDocument.Parse(line);
                var evt = document.RootElement;
                if (evt.GetProperty("version").GetInt32() != 1 || evt.GetProperty("id").GetString() != id)
                    throw new InvalidOperationException("Metadata service protocol mismatch.");
                if (evt.GetProperty("kind").GetString() == "done")
                {
                    _requests++;
                    if (!evt.GetProperty("data").GetBoolean())
                        throw new InvalidOperationException("Metadata request failed.");
                    break;
                }
                receive(evt);
            }
        }
        catch
        {
            // A damaged or timed-out connection cannot be reused. User may retry reads explicitly.
            CloseReader();
            throw;
        }
        finally { _gate.Release(); }
    }

    public void Reset() => CloseReader();
    private void CloseReader()
    {
        var process = _reader;
        _reader = null; _identity = null; _requests = 0;
        if (process == null) return;
        try
        {
            process.StandardInput.Close();
            if (!process.HasExited) process.Kill(entireProcessTree: true);
        }
        catch (InvalidOperationException) { }
        catch (IOException) { }
        catch (System.ComponentModel.Win32Exception) { }
        finally
        {
            process.Dispose();
            if (_drain != null) _ = _drain.ContinueWith(t => { _ = t.Exception; }, TaskContinuationOptions.OnlyOnFaulted);
            _drain = null;
        }
    }
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true; CloseReader();
    }
}
