using System.ComponentModel;
using System.IO;
using System.Text.Json;
using System.Windows;
using Microsoft.Win32;

namespace GridAgent.Windows;

public partial class MainWindow : Window
{
    private string? _session;
    private string? _boundWorkspace;
    private bool _busy;
    private sealed record Entry(string Id, string Label);

    public MainWindow()
    {
        InitializeComponent();
        RuntimeStatus.Text = File.Exists(BundledPython) ? "Bundled Python · ready" : "Developer runtime";
        WorkspacePath.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GridAgent");
        ModelName.Text = Environment.GetEnvironmentVariable("GRIDAGENT_MODEL") ?? "";
        BaseUrl.Text = Environment.GetEnvironmentVariable("GRIDAGENT_BASE_URL") ?? "";
        Transcript.Text = "Start a research session, open a saved study, or run an offline numerical experiment.\n";
        Loaded += async (_, _) => await Execute(new { action = "refresh" });
    }

    private static string BundledPython => Path.Combine(AppContext.BaseDirectory, "runtime", "python.exe");

    private static string ResolvePython()
    {
        if (File.Exists(BundledPython)) return BundledPython;
        // Explicit developer override only; never silently search the system PATH.
        var dev = Environment.GetEnvironmentVariable("GRIDAGENT_PYTHON");
        if (!string.IsNullOrWhiteSpace(dev) && Path.IsPathFullyQualified(dev) && File.Exists(dev)) return dev;
        throw new FileNotFoundException("Bundled research engine is missing. Reinstall GridAgent.");
    }

    private void Append(string text)
    {
        Transcript.AppendText(text + "\n\n");
        Transcript.ScrollToEnd();
    }

    private async Task Execute(object request)
    {
        if (_busy) return;
        _busy = true;
        StatusText.Text = "Working…";
        try
        {
            var root = Path.GetFullPath(WorkspacePath.Text.Trim());
            if (_boundWorkspace != root)
            {
                _boundWorkspace = root;
                _session = null;
                SessionList.ItemsSource = null;
                StudyList.ItemsSource = null;
                RunList.ItemsSource = null;
            }
            var settings = new EngineSettings(ResolvePython(), root, ModelName.Text.Trim(), BaseUrl.Text.Trim(), ApiKey.Password);
            await LocalEngine.RunAsync(settings, request, Handle);
            StatusText.Text = "Ready";
        }
        catch (Exception ex)
        {
            // Do not display raw process diagnostics or provider payloads.
            Append("Operation could not complete (" + ex.GetType().Name + "). Check application installation, workspace and model settings.");
            StatusText.Text = "Check configuration";
        }
        finally { _busy = false; }
    }

    private void Handle(JsonElement evt)
    {
        var kind = evt.GetProperty("kind").GetString();
        var data = evt.GetProperty("data");
        switch (kind)
        {
            case "session": _session = data.GetString(); break;
            case "sessions":
                SessionList.ItemsSource = data.EnumerateArray().Select(x =>
                    new Entry(x.GetProperty("id").GetString()!,
                        x.GetProperty("title").GetString() + " · " + x.GetProperty("tasks").GetInt32())).ToList();
                SessionList.SelectedItem = ((IEnumerable<Entry>)SessionList.ItemsSource).FirstOrDefault(x => x.Id == _session);
                break;
            case "studies":
                StudyList.ItemsSource = data.EnumerateArray().Select(x =>
                {
                    var id = x.GetProperty("id").GetString()!;
                    return new Entry(id, id[..Math.Min(12, id.Length)] + " · " + x.GetProperty("status").GetString());
                }).ToList();
                break;
            case "runs":
                RunList.ItemsSource = data.EnumerateArray().Select(x =>
                {
                    var id = x.GetProperty("id").GetString()!;
                    return new Entry(id, x.GetProperty("operation").GetString() + " · " + id[..Math.Min(8, id.Length)]);
                }).ToList();
                break;
            case "waveform":
                var channels = data.EnumerateArray().Select(x => new WaveformSeries(
                    x.GetProperty("channel").GetString()!,
                    x.GetProperty("time").EnumerateArray().Select(v => v.GetDouble()).ToArray(),
                    x.GetProperty("value").EnumerateArray().Select(v => v.GetDouble()).ToArray(),
                    x.GetProperty("samples").GetInt32(),
                    x.GetProperty("minimum").GetDouble(), x.GetProperty("maximum").GetDouble())).ToList();
                new WaveformWindow(channels) { Owner = this }.Show();
                break;
            case "user": Append("You\n" + data.GetString()); break;
            case "assistant": Append(data.GetString() ?? ""); break;
            case "tool": Append("  " + data.GetString()); break;
            case "result": Append(data.GetString() ?? ""); break;
            case "status": StatusText.Text = data.GetString(); break;
            case "error": Append(data.GetString() ?? "Operation failed."); break;
        }
    }

    private bool WorkspaceChanged()
    {
        try { return _boundWorkspace != Path.GetFullPath(WorkspacePath.Text.Trim()); }
        catch (Exception) { return true; }
    }

    private async void Refresh(object sender, RoutedEventArgs e) => await Execute(new { action = "refresh" });

    private async void NewSession(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        Transcript.Clear();
        await Execute(new { action = "new" });
    }

    private async void OpenSession(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || SessionList.SelectedItem is not Entry row) return;
        _session = row.Id;
        Transcript.Clear();
        await Execute(new { action = "history", session = row.Id });
    }

    private async void Send(object sender, RoutedEventArgs e)
    {
        if (_busy || string.IsNullOrWhiteSpace(Prompt.Text)) return;
        if (WorkspaceChanged()) _session = null;
        string question = Prompt.Text.Trim();
        Prompt.Clear();
        Append("You\n" + question);
        await Execute(new { action = "ask", session = _session, prompt = question, budget = 3 });
    }

    private Task Local(string command, params string[] args) => Execute(new { action = "local", command, args });
    private async void OpenStudy(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || StudyList.SelectedItem is not Entry row) return;
        await Local("study", row.Id);
    }
    private async void OpenWaveform(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || RunList.SelectedItem is not Entry row) return;
        await Execute(new { action = "waveform", run = row.Id });
    }
    private async void ResumeDsr(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || StudyList.SelectedItem is not Entry row) return;
        await Local("resume-dsr", row.Id);
    }
    private async void PaperDmq(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "Dedicated DMView profile (*.json)|*.json", CheckFileExists = true };
        if (picker.ShowDialog(this) == true) await Local("paper-dmq", picker.FileName);
    }
    private async void ImportModel(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "ANDES workbook (*.xlsx)|*.xlsx", CheckFileExists = true };
        if (picker.ShowDialog(this) == true) await Local("import-model", picker.FileName);
    }
    private async void Models(object sender, RoutedEventArgs e) => await Local("models");
    private async void Backends(object sender, RoutedEventArgs e) => await Local("backends");
    private async void NativeProgram(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "Simulation program (*.json)|*.json", CheckFileExists = true };
        if (picker.ShowDialog(this) == true) await Local("native-program", picker.FileName);
    }
    private async void ImportKnowledge(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "Engineering reference pack (*.json)|*.json", CheckFileExists = true };
        if (picker.ShowDialog(this) == true) await Local("import-knowledge", picker.FileName);
    }
    private async void Knowledge(object sender, RoutedEventArgs e) => await Local("knowledge");
    private async void PaperMitigation(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "Dedicated mitigation profile (*.json)|*.json", CheckFileExists = true };
        if (picker.ShowDialog(this) == true) await Local("paper-mitigate", picker.FileName);
    }
    private async void PaperDsr(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "Dedicated PowerFactory profile (*.json)|*.json", CheckFileExists = true };
        if (picker.ShowDialog(this) == true) await Local("paper-dsr", picker.FileName);
    }
    private async void PaperRank(object sender, RoutedEventArgs e) => await Local("paper-rank");
    private async void PaperKpi(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "PowerFactory CSV (*.csv)|*.csv", CheckFileExists = true };
        if (picker.ShowDialog(this) != true) return;
        // Paper case fault starts at 1 s; explicitly request the absolute clearing time.
        var dialog = new ClearingTimeWindow { Owner = this };
        if (dialog.ShowDialog() == true) await Local("paper-kpi", picker.FileName, dialog.Value);
    }
    private async void Dmq(object sender, RoutedEventArgs e) => await Execute(new { action = "dmq", reference = false });
    private async void DmqReference(object sender, RoutedEventArgs e) => await Execute(new { action = "dmq", reference = true });
    private async void Eigen(object sender, RoutedEventArgs e) => await Local("eigen");
    private async void Optimize(object sender, RoutedEventArgs e) => await Local("optimize", "24");
    private async void Runs(object sender, RoutedEventArgs e) => await Local("runs");
    private async void Dsr(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "Candidate manifest (*.json)|*.json", CheckFileExists = true };
        if (picker.ShowDialog(this) == true)
            await Execute(new { action = "dsr", manifest = picker.FileName });
    }

    protected override void OnClosing(CancelEventArgs e)
    {
        if (_busy)
        {
            e.Cancel = true;
            MessageBox.Show(this, "A local research task is active. Close after it completes to preserve experiment records.",
                            "GridAgent", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        base.OnClosing(e);
    }
}
