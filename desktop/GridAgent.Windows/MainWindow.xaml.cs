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
    private EngineSettings? _activeEngine;
    private string? _activeResearch;
    private bool _cancellingResearch;
    private JsonElement _pluginCatalog;
    private JsonElement _topology;
    private sealed record Entry(string Id, string Label, string? Info = null);

    public MainWindow()
    {
        InitializeComponent();
        RuntimeStatus.Text = File.Exists(BundledPython) ? "Bundled Python · ready" : "Developer runtime";
        WorkspacePath.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GridAgent");
        ModelName.Text = Environment.GetEnvironmentVariable("GRIDAGENT_MODEL") ?? "";
        BaseUrl.Text = Environment.GetEnvironmentVariable("GRIDAGENT_BASE_URL") ?? "";
        Transcript.Text = "Start a research session, open a saved study, or run an offline numerical experiment.\n";
        Loaded += async (_, _) =>
        {
            if (string.IsNullOrWhiteSpace(ModelName.Text)) await Execute(new { action = "model-settings" });
            ModelConfiguration.IsExpanded = string.IsNullOrWhiteSpace(ModelName.Text);
            await Execute(new { action = "refresh" });
        };
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
                ResearchList.ItemsSource = null;
                ModelRevisions.ItemsSource = null;
            }
            var settings = new EngineSettings(ResolvePython(), root, ModelName.Text.Trim(), BaseUrl.Text.Trim(), ApiKey.Password);
            _activeEngine = settings;
            await LocalEngine.RunAsync(settings, request, Handle);
            StatusText.Text = "Ready";
        }
        catch (Exception ex)
        {
            // Do not display raw process diagnostics or provider payloads.
            Append("Operation could not complete (" + ex.GetType().Name + "). Check application installation, workspace and model settings.");
            StatusText.Text = "Check configuration";
        }
        finally { _busy = false; _activeEngine = null; _activeResearch = null; }
    }

    private void Handle(JsonElement evt)
    {
        var kind = evt.GetProperty("kind").GetString();
        var data = evt.GetProperty("data");
        switch (kind)
        {
            case "plugins": _pluginCatalog = data.Clone(); break;
            case "model_settings":
                ModelName.Text = data.GetProperty("model").GetString() ?? "";
                BaseUrl.Text = data.GetProperty("base_url").GetString() ?? "";
                break;
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
            case "research_tasks":
                var selected = (ResearchList.SelectedItem as Entry)?.Id ?? _activeResearch;
                var tasks = data.EnumerateArray().Select(x => new Entry(x.GetProperty("id").GetString()!,
                    x.GetProperty("stage").GetString() + " · " + x.GetProperty("prompt").GetString())).ToList();
                ResearchList.ItemsSource = tasks;
                ResearchList.SelectedItem = tasks.FirstOrDefault(x => x.Id == selected);
                break;
            case "research_task":
                var researchId = data.GetProperty("id").GetString();
                var stage = data.GetProperty("stage").GetString();
                if (_activeResearch != researchId || stage is "passed" or "failed" or "cancelled" or "awaiting_input" or "awaiting_approval")
                    Append(data.GetProperty("summary").GetString() ?? "");
                _activeResearch = researchId;
                StatusText.Text = $"Research · {stage} · {data.GetProperty("runs_used")} simulations";
                break;
            case "topology": _topology = data.Clone(); break;
            case "model_revisions":
                ModelRevisions.ItemsSource = data.EnumerateArray().Select(x =>
                {
                    var diff = x.GetProperty("diff");
                    return new Entry(x.GetProperty("id").GetString()!, x.GetProperty("name").GetString()!,
                        $"{diff.GetProperty("element")} {diff.GetProperty("index")} · {diff.GetProperty("field")} · " +
                        $"{diff.GetProperty("before")} → {diff.GetProperty("value")}\nParent run {x.GetProperty("parent_run")}\n" +
                        $"SHA-256 {x.GetProperty("sha256")}");
                }).ToList();
                break;
            case "analysis_charts":
                var charts = data.EnumerateArray().Select(chart => new ChartData(chart.GetProperty("title").GetString()!,
                    chart.GetProperty("x_label").GetString()!, chart.GetProperty("y_label").GetString()!,
                    chart.GetProperty("scatter").GetBoolean(), chart.GetProperty("series").EnumerateArray().Select(trace =>
                        new ChartTrace(trace.GetProperty("name").GetString()!,
                            trace.GetProperty("x").EnumerateArray().Select(x => x.GetDouble()).ToArray(),
                            trace.GetProperty("y").EnumerateArray().Select(y => y.GetDouble()).ToArray())).ToArray())).ToArray();
                new ScientificChartWindow(charts) { Owner = this }.Show();
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
    private async void OpenWorkspace(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFolderDialog { Title = "Open research workspace" };
        if (picker.ShowDialog(this) != true) return;
        WorkspacePath.Text = picker.FolderName;
        ApiKey.Clear();
        await Execute(new { action = "model-settings" });
        await Execute(new { action = "refresh" });
    }
    private async void LoadModelSettings(object sender, RoutedEventArgs e) => await Execute(new { action = "model-settings" });
    private async void SaveModelSettings(object sender, RoutedEventArgs e) =>
        await Execute(new { action = "model-save", model = ModelName.Text, base_url = BaseUrl.Text });
    private async void TestModelConnection(object sender, RoutedEventArgs e) =>
        await Execute(new { action = "model-test", model = ModelName.Text, base_url = BaseUrl.Text });

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
    private Task Research(string command, params string[] args) => Execute(new { action = "research", command, args });

    private async Task StartResearchTask(bool multi)
    {
        if (_busy || string.IsNullOrWhiteSpace(Prompt.Text)) return;
        var prompt = Prompt.Text.Trim();
        Prompt.Clear();
        await Research(multi ? "research-multi" : "research", prompt);
    }

    private async void StartResearch(object sender, RoutedEventArgs e) => await StartResearchTask(false);
    private async void StartMultiResearch(object sender, RoutedEventArgs e) => await StartResearchTask(true);

    private async void StartResearchManifest(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "Research manifest (*.json)|*.json", CheckFileExists = true };
        if (picker.ShowDialog(this) == true) await Research("research-manifest", picker.FileName);
    }

    private async void PythonSettings(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var result = MessageBox.Show(this, "Enable automatic execution of generated Python in Windows Sandbox " +
            "for this workspace? Select No to disable automatic execution.", "Automatic Python execution",
            MessageBoxButton.YesNoCancel, MessageBoxImage.Question, MessageBoxResult.Cancel);
        if (result != MessageBoxResult.Cancel)
            await Research("research-sandbox", result == MessageBoxResult.Yes ? "enable" : "disable");
    }

    private async void RunVerifiedPython(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "Research manifest (*.json)|*.json", CheckFileExists = true };
        if (picker.ShowDialog(this) == true) await Research("research-python", picker.FileName);
    }

    private async void ResearchStatus(object sender, RoutedEventArgs e)
    {
        if (!WorkspaceChanged() && ResearchList.SelectedItem is Entry row) await Research("research-status", row.Id);
    }

    private async void ResumeResearch(object sender, RoutedEventArgs e)
    {
        if (!WorkspaceChanged() && ResearchList.SelectedItem is Entry row) await Research("research-resume", row.Id);
    }

    private async void ApproveResearch(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || ResearchList.SelectedItem is not Entry row) return;
        if (MessageBox.Show(this, "Authorize the repair ranges shown in this task's details?", "Authorize repair",
            MessageBoxButton.OKCancel) == MessageBoxResult.OK) await Research("research-approve", row.Id);
    }

    private async void ClarifyResearch(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || ResearchList.SelectedItem is not Entry row ||
            string.IsNullOrWhiteSpace(Prompt.Text)) return;
        var answer = Prompt.Text.Trim();
        Prompt.Clear();
        await Research("research-clarify", row.Id, answer);
    }

    private async void ExportResearch(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || ResearchList.SelectedItem is not Entry row) return;
        var picker = new SaveFileDialog { Filter = "Research report (*.json)|*.json", FileName = "research-" + row.Id };
        if (picker.ShowDialog(this) == true) await Research("research-report", row.Id, picker.FileName);
    }

    private async void CancelResearch(object sender, RoutedEventArgs e)
    {
        if (_cancellingResearch || WorkspaceChanged()) return;
        if (!_busy)
        {
            if (ResearchList.SelectedItem is Entry row) await Research("research-cancel", row.Id);
            return;
        }
        if (_activeEngine is not EngineSettings settings || _activeResearch is not string id) return;
        _cancellingResearch = true;
        try
        {
            await LocalEngine.RunAsync(settings, new { action = "research", command = "research-cancel", args = new[] { id } }, _ => { });
            StatusText.Text = "Cancellation requested";
        }
        catch (InvalidOperationException)
        {
            Append("The task could not be cancelled.");
        }
        finally { _cancellingResearch = false; }
    }
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
    private async void OverlayWaveforms(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged()) return;
        var runs = RunList.SelectedItems.Cast<Entry>().Select(row => row.Id).ToArray();
        if (runs.Length is < 2 or > 4) { Append("Select two to four waveform runs for comparison."); return; }
        await Execute(new { action = "waveform-overlay", runs });
    }
    private async void OpenScientificCharts(object sender, RoutedEventArgs e)
    {
        if (!_busy && !WorkspaceChanged() && RunList.SelectedItem is Entry row)
            await Execute(new { action = "analysis-charts", run = row.Id });
    }
    private async void OpenTopology(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || RunList.SelectedItem is not Entry row) return;
        _topology = default;
        await Execute(new { action = "topology", run = row.Id });
        if (_topology.ValueKind != JsonValueKind.Object) return;
        var nodes = _topology.GetProperty("nodes").EnumerateArray().Select(x => new TopologyNode(
            x.GetProperty("id").GetInt32(), x.GetProperty("kv").GetDouble(), x.GetProperty("active").GetBoolean())).ToArray();
        var links = _topology.GetProperty("links").EnumerateArray().Select(x => new TopologyLink(
            x.GetProperty("from").GetInt32(), x.GetProperty("to").GetInt32(), x.GetProperty("type").GetString()!,
            x.GetProperty("closed").GetBoolean())).ToArray();
        var devices = _topology.GetProperty("devices").EnumerateArray().Select(x => new ModelParameter(
            x.GetProperty("element").GetString()!, x.GetProperty("index").GetInt32(), x.GetProperty("field").GetString()!,
            x.GetProperty("value").GetRawText())).ToArray();
        var dialog = new TopologyWindow(nodes, links, devices) { Owner = this };
        if (dialog.ShowDialog() == true && dialog.Edit != null)
            await Execute(new { action = "save-model-revision", run = row.Id, edit = dialog.Edit });
    }
    private void ModelRevisionDiff(object sender, RoutedEventArgs e)
    {
        if (!WorkspaceChanged() && ModelRevisions.SelectedItem is Entry row && row.Info != null) Append(row.Info);
    }
    private async void RunModelRevision(object sender, RoutedEventArgs e)
    {
        if (!_busy && !WorkspaceChanged() && ModelRevisions.SelectedItem is Entry row)
            await Execute(new { action = "run-model-revision", revision = row.Id });
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
    private async void PluginCenter(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        _pluginCatalog = default;
        await Execute(new { action = "plugins" });
        if (_pluginCatalog.ValueKind != JsonValueKind.Array) return;
        var dialog = new PluginCenterWindow(_pluginCatalog) { Owner = this };
        if (dialog.ShowDialog() == true && dialog.SelectedId != null && dialog.Command != null)
            await Local(dialog.Command, dialog.SelectedId);
    }
    private async void RegisterNgspice(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "ngspice console (ngspice_con.exe;ngspice.exe)|ngspice_con.exe;ngspice.exe",
            CheckFileExists = true };
        if (picker.ShowDialog(this) == true) await Local("register-ngspice", picker.FileName);
    }
    private void ReviewScript(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        try
        {
            var root = Path.GetFullPath(WorkspacePath.Text.Trim());
            var drafts = Path.Combine(root, "drafts");
            Directory.CreateDirectory(drafts);
            var picker = new OpenFileDialog { Filter = "Python source (*.py)|*.py", InitialDirectory = drafts,
                                              CheckFileExists = true };
            if (picker.ShowDialog(this) != true) return;
            var source = File.ReadAllText(picker.FileName);
            if (System.Text.Encoding.UTF8.GetByteCount(source) > 65536)
                throw new InvalidOperationException("Source exceeds 64 KiB.");
            var review = new ScriptReviewWindow(source) { Owner = this };
            if (review.ShowDialog() != true) return;
            var output = SandboxRunner.Launch(root, source);
            Append("Windows Sandbox launch requested. Review outputs manually in: " + output +
                   ". No numerical result is verified yet.");
        }
        catch (Exception ex)
        {
            Append("Sandbox could not launch (" + ex.GetType().Name +
                   "). Windows Sandbox and the bundled runtime must be installed.");
        }
    }
    private async void Experience(object sender, RoutedEventArgs e) => await Local("experience");
    private async void ModelingBenchmark(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var choice = new Window { Title = "Modeling benchmark", Width = 400, Height = 210,
            Owner = this, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        var panel = new System.Windows.Controls.StackPanel { Margin = new Thickness(20) };
        var tasks = new System.Windows.Controls.ComboBox { Margin = new Thickness(0, 10, 0, 16) };
        tasks.Items.Add("two-bus"); tasks.Items.Add("storage-dispatch");
        tasks.Items.Add("source-short-circuit"); tasks.Items.Add("lossy-storage"); tasks.Items.Add("lossy-link");
        tasks.SelectedIndex = 0;
        panel.Children.Add(new System.Windows.Controls.TextBlock { Text = "Generate, test and repair a model (up to six attempts)." });
        panel.Children.Add(tasks);
        var run = new System.Windows.Controls.Button { Content = "Run benchmark", IsDefault = true };
        run.Click += (_, _) => choice.DialogResult = true;
        panel.Children.Add(run); choice.Content = panel;
        if (choice.ShowDialog() == true && tasks.SelectedItem is string task)
            await Local("modeling-benchmark", task);
    }
    private async void ModelRepair(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "Benchmark repair manifest (*.json)|*.json", CheckFileExists = true };
        if (picker.ShowDialog(this) != true) return;
        if (MessageBox.Show(this, "Run the fixed evaluator and allow up to five repairs of the manifest's explicit editable parameters? This uses your model API.", "Authorize benchmark repair", MessageBoxButton.OKCancel) == MessageBoxResult.OK)
            await Local("model-repair", picker.FileName);
    }
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
    private async void AndesBatch(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = new OpenFileDialog { Filter = "ANDES batch (*.json)|*.json", CheckFileExists = true };
        if (picker.ShowDialog(this) == true) await Local("andes-batch", picker.FileName);
    }
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
