using System.IO;
using System.Collections.ObjectModel;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Windowing;
using Windows.Storage.Pickers;
using Windows.System;

namespace GridAgent.Windows;

public partial class MainWindow : Window
{
    private string? _session;
    private string? _boundWorkspace;
    private readonly ObservableCollection<ConversationMessage> _messages = new();
    private bool _workspaceIndexLoaded;
    private bool _initialized;
    private bool _busy;
    private bool _operationError;
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
        Messages.ItemsSource = _messages;
        ModelName.TextChanged += (_, _) => UpdateModelCaption();
        UpdateModelCaption();
        Title = "GridAgent";
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        SystemBackdrop = new MicaBackdrop();
        AppWindow.Resize(new global::Windows.Graphics.SizeInt32(1200, 840));
        AppWindow.Closing += (_, args) => { if (_busy) { args.Cancel = true; Notify("A research operation is active. Wait for completion or cancel the research task.", InfoBarSeverity.Warning); } };
        Navigation.SelectedItem = AssistantNavigation;
        Root.Loaded += async (_, _) =>
        {
            await Execute(new { action = "initialize" });
            _initialized = true;
            if (string.IsNullOrWhiteSpace(ModelName.Text)) { Navigation.SelectedItem = Navigation.SettingsItem; Notify("Configure a model provider to use the assistant. Offline tools are available without one.", InfoBarSeverity.Informational); }
            await EnsureWorkspaceIndex();
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

    private ConversationMessage? _toolGroup;
    private void ClearMessages() { _messages.Clear(); _toolGroup = null; EmptyConversation.Visibility = Visibility.Visible; }
    private void Notify(string message, InfoBarSeverity severity = InfoBarSeverity.Informational)
    {
        Notice.Message = message; Notice.Severity = severity; Notice.IsOpen = true;
    }
    private void UpdateModelCaption() => ConversationModel.Text = string.IsNullOrWhiteSpace(ModelName.Text) ? "Engineering assistant" : ModelName.Text.Trim();
    private void OpenConversationHistory(object sender, RoutedEventArgs e) =>
        Navigation.SelectedItem = Navigation.MenuItems.OfType<NavigationViewItem>().First(i => (string)i.Tag == "studies");
    private void UseSuggestion(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Content is string text) { Prompt.Text = text; Prompt.Focus(FocusState.Programmatic); }
    }
    private bool _scrollQueued;
    private void QueueConversationScroll()
    {
        if (_scrollQueued || _messages.Count == 0) return;
        // Coalesce bursts of history and tool updates into one dispatcher callback.
        _scrollQueued = true;
        DispatcherQueue.TryEnqueue(() =>
        {
            _scrollQueued = false;
            if (_messages.Count > 0) Messages.ScrollIntoView(_messages[^1]);
        });
    }
    private void Append(string text, string role = "Result")
    {
        if (string.IsNullOrWhiteSpace(text)) return;
        _toolGroup = null;
        EmptyConversation.Visibility = Visibility.Collapsed;
        _messages.Add(new ConversationMessage(role, text));
        QueueConversationScroll();
    }
    private void AddTool(string label)
    {
        EmptyConversation.Visibility = Visibility.Collapsed;
        // Only the bridge's sanitized tool summary is accepted; no raw execution payload.
        if (_toolGroup == null)
        {
            _toolGroup = new ConversationMessage("Activity", "");
            _messages.Add(_toolGroup);
        }
        _toolGroup.AddActivity(label);
        QueueConversationScroll();
    }
    private async void Navigate(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (Pages == null) return;
        var tag = args.IsSettingsSelected ? "settings" : (args.SelectedItemContainer as NavigationViewItem)?.Tag as string ?? "chat";
        foreach (var (page, key) in new (UIElement, string)[] { (ChatPage,"chat"),(TasksPage,"tasks"),(ModelsPage,"models"),(RunsPage,"runs"),(StudiesPage,"studies"),(ToolsPage,"tools"),(PluginsPage,"plugins"),(KnowledgePage,"knowledge"),(SettingsPage,"settings") })
            page.Visibility = tag == key ? Visibility.Visible : Visibility.Collapsed;
        if (!_initialized) return;
        if (tag == "plugins" && _pluginCatalog.ValueKind != JsonValueKind.Array && !_busy) PluginCenter(this, new RoutedEventArgs());
        else await EnsureWorkspaceIndex();
    }
    private Task EnsureWorkspaceIndex()
    {
        var tag = (Navigation.SelectedItem as NavigationViewItem)?.Tag as string;
        return !_workspaceIndexLoaded && !_busy && tag is ("tasks" or "models" or "runs" or "studies")
            ? Execute(new { action = "refresh" }) : Task.CompletedTask;
    }
    private void ShowChat() => Navigation.SelectedItem = AssistantNavigation;
    private void ChangeTheme(object sender, SelectionChangedEventArgs e)
    {
        if (Root != null && sender is ComboBox choice)
            Root.RequestedTheme = choice.SelectedIndex == 1 ? ElementTheme.Light : choice.SelectedIndex == 2 ? ElementTheme.Dark : ElementTheme.Default;
    }
    private void PromptKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Enter && Microsoft.UI.Input.InputKeyboardSource.GetKeyStateForCurrentThread(VirtualKey.Control).HasFlag(global::Windows.UI.Core.CoreVirtualKeyStates.Down))
        { e.Handled = true; Send(sender, new RoutedEventArgs()); }
    }
    private void SetBusy(bool busy)
    {
        _busy = busy;
        BusyRing.IsActive = busy;
        BusyRing.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
        SendButton.IsEnabled = !busy;
        CancelButton.Visibility = busy && _activeResearch != null ? Visibility.Visible : Visibility.Collapsed;
    }

    private async Task Execute(object request)
    {
        if (_busy) { Notify("Another operation is running.", InfoBarSeverity.Warning); return; }
        SetBusy(true);
        _operationError = false;
        StatusText.Text = "Working…";
        try
        {
            var root = Path.GetFullPath(WorkspacePath.Text.Trim());
            if (_boundWorkspace != root)
            {
                _workspaceIndexLoaded = false;
                _pluginCatalog = default;
                PluginRows.Children.Clear();
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
            StatusText.Text = _operationError ? "Operation failed" : "Ready";
        }
        catch (Exception ex)
        {
            _operationError = true;
            // Do not display raw process diagnostics or provider payloads.
            Append("Operation could not complete (" + ex.GetType().Name + "). Check application installation, workspace and model settings.");
            StatusText.Text = "Check configuration";
            Notify("Operation could not complete. Check the workspace, runtime and provider.", InfoBarSeverity.Error);
        }
        finally { SetBusy(false); _activeEngine = null; _activeResearch = null; }
    }

    private void Handle(JsonElement evt)
    {
        var kind = evt.GetProperty("kind").GetString();
        var data = evt.GetProperty("data");
        switch (kind)
        {
            case "plugins": _pluginCatalog = data.Clone(); RenderPlugins(); break;
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
                CancelButton.Visibility = _busy && stage is not ("passed" or "failed" or "cancelled" or "awaiting_input" or "awaiting_approval") ? Visibility.Visible : Visibility.Collapsed;
                StatusText.Text = $"Research · {stage} · {data.GetProperty("runs_used")}/{data.GetProperty("max_runs")} simulations";
                break;
            case "topology": _topology = data.Clone(); break;
            case "model_revisions":
                _workspaceIndexLoaded = true;
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
                ShowCharts(charts);
                break;
            case "waveform":
                var channels = data.EnumerateArray().Select(x => new WaveformSeries(
                    x.GetProperty("channel").GetString()!,
                    x.GetProperty("time").EnumerateArray().Select(v => v.GetDouble()).ToArray(),
                    x.GetProperty("value").EnumerateArray().Select(v => v.GetDouble()).ToArray(),
                    x.GetProperty("samples").GetInt32(),
                    x.GetProperty("minimum").GetDouble(), x.GetProperty("maximum").GetDouble())).ToList();
                ShowWaveforms(channels);
                break;
            case "user": Append(data.GetString() ?? "", "You"); break;
            case "assistant": Append(data.GetString() ?? "", "Assistant"); break;
            case "tool": AddTool(data.GetString() ?? "Tool"); break;
            case "result": Append(data.ValueKind == JsonValueKind.String ? data.GetString() ?? "" : "A structured result is available in the workspace."); break;
            case "status": StatusText.Text = data.GetString() ?? "Working…"; break;
            case "error": _operationError = true; Append(data.GetString() ?? "Operation failed.", "Error"); Notify("The operation reported an error. See the conversation for details.", InfoBarSeverity.Error); break;
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
        var picker = new FolderPicker();
        picker.FileTypeFilter.Add("*");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
        var folder = await picker.PickSingleFolderAsync();
        if (folder == null) return;
        WorkspacePath.Text = folder.Path;
        ApiKey.Password = "";
        ClearMessages();
        await Execute(new { action = "initialize" });
        await EnsureWorkspaceIndex();
    }
    private async void LoadModelSettings(object sender, RoutedEventArgs e) => await Execute(new { action = "model-settings" });
    private async void SaveModelSettings(object sender, RoutedEventArgs e) =>
        await Execute(new { action = "model-save", model = ModelName.Text, base_url = BaseUrl.Text });
    private async void TestModelConnection(object sender, RoutedEventArgs e) =>
        await Execute(new { action = "model-test", model = ModelName.Text, base_url = BaseUrl.Text });

    private async void NewSession(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        ClearMessages(); ShowChat();
        await Execute(new { action = "new", lightweight = true });
    }

    private async void OpenSession(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || SessionList.SelectedItem is not Entry row) return;
        _session = row.Id;
        ClearMessages(); ShowChat();
        await Execute(new { action = "history", session = row.Id });
    }

    private async void Send(object sender, RoutedEventArgs e)
    {
        if (_busy || string.IsNullOrWhiteSpace(Prompt.Text)) return;
        if (Mode.SelectedIndex != 0) { await StartResearchTask(Mode.SelectedIndex == 2); return; }
        if (WorkspaceChanged()) _session = null;
        string question = Prompt.Text.Trim();
        Prompt.Text = "";
        Append(question, "You");
        await Execute(new { action = "ask", session = _session, prompt = question, budget = 3 });
    }

    private Task Local(string command, params string[] args) { if (!command.StartsWith("plugin-")) ShowChat(); return Execute(new { action = "local", command, args }); }
    private Task Research(string command, params string[] args) { ShowChat(); return Execute(new { action = "research", command, args }); }

    private async Task StartResearchTask(bool multi)
    {
        if (_busy || string.IsNullOrWhiteSpace(Prompt.Text)) return;
        var prompt = Prompt.Text.Trim();
        Prompt.Text = ""; Append(prompt, "You"); ShowChat();
        await Research(multi ? "research-multi" : "research", prompt);
    }

    private async void StartResearch(object sender, RoutedEventArgs e) => await StartResearchTask(false);
    private async void StartMultiResearch(object sender, RoutedEventArgs e) => await StartResearchTask(true);

    private async void StartResearchManifest(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".json");
        if (picker != null) await Research("research-manifest", picker);
    }

    private async void PythonSettings(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var result = await new ContentDialog { XamlRoot = Root.XamlRoot, Title = "Automatic Python execution",
            Content = "Allow generated Python to execute in Windows Sandbox for this workspace? Network access is disabled.",
            PrimaryButtonText = "Enable", SecondaryButtonText = "Disable", CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.Close }.ShowAsync();
        if (result != ContentDialogResult.None)
            await Research("research-sandbox", result == ContentDialogResult.Primary ? "enable" : "disable");
    }

    private async void RunVerifiedPython(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".json");
        if (picker != null) await Research("research-python", picker);
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
        if (await Confirm("Authorize repair", "Authorize the repair ranges shown in this task's details?")) await Research("research-approve", row.Id);
    }

    private async void ClarifyResearch(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || ResearchList.SelectedItem is not Entry row) return;
        var answerBox = new TextBox { Header = "Clarification", AcceptsReturn = true, TextWrapping = TextWrapping.Wrap };
        if (await new ContentDialog { XamlRoot = Root.XamlRoot, Title = "Answer research question", Content = answerBox, PrimaryButtonText = "Submit", CloseButtonText = "Cancel" }.ShowAsync() != ContentDialogResult.Primary || string.IsNullOrWhiteSpace(answerBox.Text)) return;
        var answer = answerBox.Text.Trim();
        await Research("research-clarify", row.Id, answer);
    }

    private async void ExportResearch(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || ResearchList.SelectedItem is not Entry row) return;
        var picker = new FileSavePicker { SuggestedFileName = "research-" + row.Id };
        picker.FileTypeChoices.Add("JSON report", new[] { ".json" });
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
        var file = await picker.PickSaveFileAsync();
        if (file != null) await Research("research-report", row.Id, file.Path);
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
        var edit = await ShowTopology(nodes, links, devices);
        if (edit != null) await Execute(new { action = "save-model-revision", run = row.Id, edit });
    }
    private void ModelRevisionDiff(object sender, RoutedEventArgs e)
    {
        if (!WorkspaceChanged() && ModelRevisions.SelectedItem is Entry row && row.Info != null) { ShowChat(); Append(row.Info); }
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
        var picker = await PickFile(".json");
        if (picker != null) await Local("paper-dmq", picker);
    }
    private async void ImportModel(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".xlsx");
        if (picker != null) await Local("import-model", picker);
    }
    private async void Models(object sender, RoutedEventArgs e) => await Local("models");
    private async void PluginCenter(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        _pluginCatalog = default;
        await Execute(new { action = "plugins" });
        if (_pluginCatalog.ValueKind != JsonValueKind.Array) return;
        RenderPlugins();
    }
    private async void RegisterNgspice(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".exe");
        if (picker != null) await Local("register-ngspice", picker);
    }
    private async void ReviewScript(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        try
        {
            var root = Path.GetFullPath(WorkspacePath.Text.Trim());
            var drafts = Path.Combine(root, "drafts");
            Directory.CreateDirectory(drafts);
            var path = await PickFile(".py");
            if (path == null) return;
            var source = File.ReadAllText(path);
            if (System.Text.Encoding.UTF8.GetByteCount(source) > 65536)
                throw new InvalidOperationException("Source exceeds 64 KiB.");
            var review = new TextBox { Text = source, IsReadOnly = true, AcceptsReturn = true, TextWrapping = TextWrapping.NoWrap, MaxHeight = 420, FontFamily = new FontFamily("Consolas") };
            if (await new ContentDialog { XamlRoot = Root.XamlRoot, Title = "Review source · isolated Windows Sandbox", Content = review, PrimaryButtonText = "Approve and launch", CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.Close }.ShowAsync() != ContentDialogResult.Primary) return;
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
        var tasks = new ComboBox { ItemsSource = new[] { "two-bus", "storage-dispatch", "source-short-circuit", "lossy-storage", "lossy-link" }, SelectedIndex = 0, Header = "Benchmark task" };
        if (await new ContentDialog { XamlRoot = Root.XamlRoot, Title = "Modeling benchmark", Content = tasks, PrimaryButtonText = "Run benchmark", CloseButtonText = "Cancel" }.ShowAsync() == ContentDialogResult.Primary && tasks.SelectedItem is string task)
            await Local("modeling-benchmark", task);
    }
    private async void ModelRepair(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".json");
        if (picker == null) return;
        if (await Confirm("Authorize benchmark repair", "Run the fixed evaluator and allow up to five repairs of the manifest's explicit editable parameters? This uses your model API."))
            await Local("model-repair", picker);
    }
    private async void NativeProgram(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".json");
        if (picker != null) await Local("native-program", picker);
    }
    private async void ImportKnowledge(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".json");
        if (picker != null) await Local("import-knowledge", picker);
    }
    private async void Knowledge(object sender, RoutedEventArgs e) => await Local("knowledge");
    private async void PaperMitigation(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".json");
        if (picker != null) await Local("paper-mitigate", picker);
    }
    private async void PaperDsr(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".json");
        if (picker != null) await Local("paper-dsr", picker);
    }
    private async void PaperRank(object sender, RoutedEventArgs e) => await Local("paper-rank");
    private async void PaperKpi(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".csv");
        if (picker == null) return;
        // Paper case fault starts at 1 s; explicitly request the absolute clearing time.
        var time = new NumberBox { Header = "Absolute clearing time (s)", Minimum = 1, Value = 1.1 };
        if (await new ContentDialog { XamlRoot = Root.XamlRoot, Title = "Fault clearing time", Content = time, PrimaryButtonText = "Evaluate", CloseButtonText = "Cancel" }.ShowAsync() == ContentDialogResult.Primary && double.IsFinite(time.Value) && time.Value > 1)
            await Local("paper-kpi", picker, time.Value.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }
    private async void Dmq(object sender, RoutedEventArgs e) { ShowChat(); await Execute(new { action = "dmq", reference = false }); }
    private async void DmqReference(object sender, RoutedEventArgs e) { ShowChat(); await Execute(new { action = "dmq", reference = true }); }
    private async void Eigen(object sender, RoutedEventArgs e) => await Local("eigen");
    private async void AndesBatch(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".json");
        if (picker != null) await Local("andes-batch", picker);
    }
    private async void Optimize(object sender, RoutedEventArgs e) => await Local("optimize", "24");
    private async void Runs(object sender, RoutedEventArgs e) => await Execute(new { action = "refresh" });
    private async void Dsr(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".json");
        if (picker != null) { ShowChat(); await Execute(new { action = "dsr", manifest = picker }); }
    }

    private async Task<string?> PickFile(string extension)
    {
        var picker = new FileOpenPicker();
        picker.FileTypeFilter.Add(extension);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
        var file = await picker.PickSingleFileAsync();
        return file?.Path;
    }
    private async Task<bool> Confirm(string title, string message) =>
        await new ContentDialog { XamlRoot = Root.XamlRoot, Title = title, Content = message, PrimaryButtonText = "Continue",
            CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.Close }.ShowAsync() == ContentDialogResult.Primary;
}

