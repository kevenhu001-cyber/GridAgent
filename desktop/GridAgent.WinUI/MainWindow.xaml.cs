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
    private readonly ConversationState _conversation = new();
    private ReadOnlyObservableCollection<ConversationMessage> _messages => _conversation.Messages;
    private readonly DesktopEngineClient _engine = new();
    private bool _workspaceIndexLoaded;
    private List<Entry> _sessions = new();
    private bool _initialized;
    private bool _loadingTheme;
    private bool _busy;
    private bool _operationError;
    private bool _conversationOperation;
    private bool _sessionsLoaded;
    private bool _knowledgeLoaded;
    private EngineSettings? _activeEngine;
    private string? _activeResearch;
    private bool _cancellingResearch;
    private JsonElement _pluginCatalog;
    private JsonElement _topology;
    private JsonElement _knowledgePage;
    private sealed record Entry(string Id, string Label, string? Info = null, string? Summary = null);

    private bool _layoutReady;
    private bool _launchInitialized;
    private bool _uiSmokeActive;
    public MainWindow(bool skipOnboarding = false)
    {
        StartupDiagnostics.Record("window.xaml.begin");
        InitializeComponent();
        StartupDiagnostics.Record("window.xaml.complete");
        _layoutReady = true;
        ChatPage.SizeChanged += (_, e) => ChatPage.Padding = new Thickness(e.NewSize.Width < 560 ? 8 : 16, 16, e.NewSize.Width < 560 ? 8 : 16, 16);
        RuntimeStatus.Text = File.Exists(BundledPython) ? "Bundled Python · ready" : "Developer runtime";
        WorkspacePath.Text = SetupPreferences.LoadWorkspace() ?? AppDataPaths.DefaultWorkspace;
        ModelName.Text = Environment.GetEnvironmentVariable("GRIDAGENT_MODEL") ?? "";
        BaseUrl.Text = Environment.GetEnvironmentVariable("GRIDAGENT_BASE_URL") ?? "";
        Messages.ItemsSource = _messages;
        LoadTheme();
        Root.RequestedTheme = Theme.SelectedIndex == 1 ? ElementTheme.Light : Theme.SelectedIndex == 2 ? ElementTheme.Dark : ElementTheme.Default;
        ModelName.TextChanged += (_, _) => UpdateModelCaption();
        UpdateModelCaption();
        Title = "GridAgent";
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        SystemBackdrop = new MicaBackdrop();
        var appIcon = Path.Combine(AppContext.BaseDirectory, "BrandAssets", "GridAgent.ico");
        if (File.Exists(appIcon)) AppWindow.SetIcon(appIcon);
        AppWindow.Resize(new global::Windows.Graphics.SizeInt32(1200, 840));
        AppWindow.Closing += (_, args) => { if (_busy) { args.Cancel = true; Notify("A research operation is active. Wait for completion or cancel the research task.", InfoBarSeverity.Warning); } };
        Closed += (_, _) => _engine.Dispose();
        Navigation.SelectedItem = AssistantNavigation;
        Root.Loaded += async (_, _) =>
        {
            if (_launchInitialized) return;
            _launchInitialized = true;
            StartupDiagnostics.Record("window.loaded");
            // The development smoke uses its own isolated workspace and bridge.
            // Avoid racing its process-wide plugin settings with normal initialization.
            if (skipOnboarding) { _initialized = true; return; }
            await Execute(new { action = "initialize" });
            _initialized = true;
            if (!skipOnboarding && !SetupPreferences.Completed) await ShowSetupAsync();
            else if (!skipOnboarding && string.IsNullOrWhiteSpace(ModelName.Text)) Notify("Configure a model provider in Settings to use the assistant. Offline tools are available without one.", InfoBarSeverity.Informational);
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

    private async void Navigate(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (!_layoutReady || (args.SelectedItemContainer as NavigationViewItem)?.Tag is Entry) return;
        var tag = args.IsSettingsSelected ? "settings" : (args.SelectedItemContainer as NavigationViewItem)?.Tag as string ?? "chat";
        foreach (var (page, key) in new (UIElement, string)[] { (ChatPage,"chat"),(TasksPage,"tasks"),(ModelsPage,"models"),(RunsPage,"runs"),(StudiesPage,"studies"),(ToolsPage,"tools"),(PluginsPage,"plugins"),(KnowledgePage,"knowledge"),(SettingsPage,"settings") })
            page.Visibility = tag == key ? Visibility.Visible : Visibility.Collapsed;
        if (!_initialized || _uiSmokeActive) return;
        if (tag == "plugins" && _pluginCatalog.ValueKind != JsonValueKind.Array && !_busy) PluginCenter(this, new RoutedEventArgs());
        else if (tag == "knowledge" && !_busy) await Execute(new { action = "knowledge-packs" });
        else await EnsureWorkspaceIndex();
    }
    private async void NavigationInvoked(NavigationView sender, NavigationViewItemInvokedEventArgs args)
    {
        if (args.InvokedItemContainer is not NavigationViewItem item) return;
        if (item.Tag is Entry session) await OpenSessionById(session.Id);
        else if (item.Tag as string == "new-chat") NewSession(sender, new RoutedEventArgs());
        else if (item.Tag as string == "search-chat") OpenConversationHistory(sender, new RoutedEventArgs());
    }
    private void SearchSessions(object sender, TextChangedEventArgs args)
    {
        if (_layoutReady) ApplySessionFilter();
    }
    private void ApplySessionFilter()
    {
        if (SessionList == null) return;
        var query = SessionSearch?.Text.Trim() ?? "";
        var visible = _sessions.Where(s => s.Label.Contains(query, StringComparison.OrdinalIgnoreCase)).ToList();
        SessionList.ItemsSource = visible;
        SessionList.SelectedItem = visible.FirstOrDefault(s => s.Id == _session);
        SetEmpty(SessionsEmpty, _sessionsLoaded && visible.Count == 0, query.Length == 0 ? "No conversations yet." : "No matching conversations.");
    }
    private void SetSessions(List<Entry> sessions)
    {
        _sessions = sessions;
        ApplySessionFilter();
        RecentConversations.MenuItems.Clear();
        foreach (var session in sessions.Take(12))
        {
            var item = new NavigationViewItem { Content = new TextBlock { Text = session.Label, TextTrimming = TextTrimming.CharacterEllipsis, MaxLines = 1 }, Tag = session, SelectsOnInvoked = false };
            ToolTipService.SetToolTip(item, session.Label);
            RecentConversations.MenuItems.Add(item);
        }
    }
    private async Task OpenSessionById(string id)
    {
        if (_busy || WorkspaceChanged()) { Notify("Wait for the current operation or open the workspace first.", InfoBarSeverity.Warning); return; }
        _session = id;
        ClearMessages(); ShowChat();
        await Execute(new { action = "history", session = id, presentation = 1 });
        Prompt.Focus(FocusState.Programmatic);
    }
    private async void OpenArtifactRun(string id)
    {
        if (_busy) { Notify("Wait for the current operation to finish before opening a run.", InfoBarSeverity.Warning); return; }
        if (WorkspaceChanged()) return;
        if (RunList.ItemsSource is not IEnumerable<Entry> entries || !entries.Any(e => e.Id == id))
            await Execute(new { action = "refresh" });
        if (RunList.ItemsSource is IEnumerable<Entry> refreshed && refreshed.FirstOrDefault(e => e.Id == id) is Entry run)
        {
            Navigation.SelectedItem = ResultsNavigation;
            RunList.SelectedItems.Clear();
            RunList.SelectedItem = run;
            RunList.ScrollIntoView(run);
        }
        else Notify("This run is no longer available in the current workspace.", InfoBarSeverity.Warning);
    }
    private async void OpenArtifactTask(string id)
    {
        if (_busy) { Notify("Wait for the current operation before opening the task details.", InfoBarSeverity.Warning); return; }
        if (WorkspaceChanged()) return;
        if (ResearchList.ItemsSource is not IEnumerable<Entry> entries || !entries.Any(e => e.Id == id))
            await Execute(new { action = "refresh" });
        if (ResearchList.ItemsSource is IEnumerable<Entry> refreshed && refreshed.FirstOrDefault(e => e.Id == id) is Entry task)
        {
            Navigation.SelectedItem = ResearchNavigation;
            ResearchList.SelectedItem = task;
            ResearchList.ScrollIntoView(task);
        }
        else Notify("The research task is not available in this workspace.", InfoBarSeverity.Warning);
    }
    private void UpdateResearchCard(ResearchSnapshot snapshot)
    {
        _conversation.Research(snapshot, OpenArtifactTask);
        UpdateConversationViewport();
    }
    private Task EnsureWorkspaceIndex()
    {
        var tag = (Navigation.SelectedItem as NavigationViewItem)?.Tag as string;
        return !_workspaceIndexLoaded && !_busy && tag is ("tasks" or "models" or "runs" or "studies")
            ? Execute(new { action = "refresh" }) : Task.CompletedTask;
    }
    private void ShowChat() => Navigation.SelectedItem = AssistantNavigation;
    private static string ThemePreferencePath => AppDataPaths.ThemeFile;
    private void LoadTheme()
    {
        _loadingTheme = true;
        try
        {
            if (File.Exists(ThemePreferencePath) && int.TryParse(File.ReadAllText(ThemePreferencePath), out var index) && index is >= 0 and <= 2)
                Theme.SelectedIndex = index;
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        finally { _loadingTheme = false; }
    }
    private void ChangeTheme(object sender, SelectionChangedEventArgs e)
    {
        if (!_layoutReady || sender is not ComboBox choice) return;
        Root.RequestedTheme = choice.SelectedIndex == 1 ? ElementTheme.Light : choice.SelectedIndex == 2 ? ElementTheme.Dark : ElementTheme.Default;
        foreach (var window in _engineeringWindows)
            if (window.Content is FrameworkElement content) content.RequestedTheme = Root.RequestedTheme;
        if (_loadingTheme || !_initialized || choice.SelectedIndex < 0) return;
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(ThemePreferencePath)!);
            File.WriteAllText(ThemePreferencePath, choice.SelectedIndex.ToString(System.Globalization.CultureInfo.InvariantCulture));
        }
        catch (IOException) { Notify("Appearance preference could not be saved.", InfoBarSeverity.Warning); }
        catch (UnauthorizedAccessException) { Notify("Appearance preference could not be saved.", InfoBarSeverity.Warning); }
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
        UpdateSendState();
        OperationStatus.Visibility = busy || _operationError ? Visibility.Visible : Visibility.Collapsed;
        CancelButton.Visibility = busy && _activeResearch != null ? Visibility.Visible : Visibility.Collapsed;
    }

    private void PromptChanged(object sender, TextChangedEventArgs e)
    {
        if (_layoutReady) UpdateSendState();
    }
    private void UpdateSendState() => SendButton.IsEnabled = !_busy && !string.IsNullOrWhiteSpace(Prompt.Text);
    private static void SetEmpty(TextBlock view, bool show, string message)
    {
        view.Text = message;
        view.Visibility = show ? Visibility.Visible : Visibility.Collapsed;
    }
    private void RefreshEmptyStates()
    {
        SetEmpty(ResearchEmpty, _workspaceIndexLoaded && ResearchList.Items.Count == 0, "No research tasks yet.");
        SetEmpty(ModelsEmpty, _workspaceIndexLoaded && ModelRevisions.Items.Count == 0, "No model revisions yet.");
        SetEmpty(RunsEmpty, _workspaceIndexLoaded && RunList.Items.Count == 0, "No simulation results yet.");
        SetEmpty(StudiesEmpty, _workspaceIndexLoaded && StudyList.Items.Count == 0, "No saved studies yet.");
        SetEmpty(KnowledgeEmpty, _knowledgeLoaded && KnowledgePacks.Items.Count == 0, "No reference packs imported.");
    }

    private async Task Execute(object request)
    {
        if (_busy) { Notify("Another operation is running.", InfoBarSeverity.Warning); return; }
        _operationError = false;
        // Freeze the presentation destination when the operation begins, not when a response arrives.
        var action = JsonSerializer.SerializeToElement(request).GetProperty("action").GetString();
        _conversationOperation = action is "ask" or "history" or "research" ||
            action == "local" && ChatPage.Visibility == Visibility.Visible;
        Notice.IsOpen = false;
        SetBusy(true);
        _conversation.BeginOperation();
        StatusText.Text = action switch
        {
            "ask" => "Waiting for assistant…",
            "history" => "Loading conversation…",
            "refresh" => "Loading workspace…",
            "plugins" => "Loading plugins…",
            "knowledge-packs" or "knowledge-pack" => "Loading references…",
            "initialize" => "Opening workspace…",
            _ => "Working…"
        };
        try
        {
            var root = Path.GetFullPath(WorkspacePath.Text.Trim());
            if (_boundWorkspace != root)
            {
                _engine.Reset();
                _workspaceIndexLoaded = false;
                _pluginCatalog = default;
                PluginRows.Children.Clear();
                KnowledgePacks.ItemsSource = null;
                _knowledgeLoaded = false;
                _sessionsLoaded = false;
                _knowledgePage = default;
                _boundWorkspace = root;
                _session = null;
                SetSessions(new List<Entry>());
                StudyList.ItemsSource = null;
                RunList.ItemsSource = null;
                ResearchList.ItemsSource = null;
                ModelRevisions.ItemsSource = null;
                RefreshEmptyStates();
            }
            var settings = new EngineSettings(ResolvePython(), root, ModelName.Text.Trim(), BaseUrl.Text.Trim(), ApiKey.Password);
            _activeEngine = settings;
            await _engine.RunAsync(settings, request, Handle);
            StatusText.Text = _operationError ? "Operation failed" : "Ready";
        }
        catch (Exception)
        {
            _operationError = true;
            // Keep raw provider payloads and exception details out of ordinary UI.
            ReportOperationError("Operation could not complete. Check the workspace, runtime and model provider.");
            StatusText.Text = "Check configuration";
        }
        finally { InterruptStream(); SetBusy(false); RefreshEmptyStates(); _activeEngine = null; _activeResearch = null; }
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
        SetupPreferences.SaveWorkspace(folder.Path);
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
        Mode.SelectedIndex = 0;
        Prompt.Text = "";
        await Execute(new { action = "new", lightweight = true });
        Prompt.Focus(FocusState.Programmatic);
    }

    private async void OpenSession(object sender, RoutedEventArgs e)
    {
        if (SessionList.SelectedItem is Entry row) await OpenSessionById(row.Id);
    }

    private async void Send(object sender, RoutedEventArgs e)
    {
        if (_busy || string.IsNullOrWhiteSpace(Prompt.Text)) return;
        if (Mode.SelectedIndex != 0) { await StartResearchTask(Mode.SelectedIndex == 2); return; }
        if (WorkspaceChanged()) _session = null;
        string question = Prompt.Text.Trim();
        Prompt.Text = "";
        Append(question, "You");
        await Execute(new { action = "ask", session = _session, prompt = question, budget = 3, stream = StreamingToggle.IsOn, presentation = 1 });
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

    private async void ScientificExecutionSettings(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var result = await new ContentDialog { XamlRoot = Root.XamlRoot, Title = "Scientific execution (preview)",
            Content = "Authorize the assistant to create and edit project files and execute Python in Windows Sandbox. Network is disabled; each run has an isolated input snapshot and output folder. This preview does not enforce a hard CPU, process or disk quota. Only enable for a trusted research workspace.",
            PrimaryButtonText = "Enable", SecondaryButtonText = "Disable", CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.Close }.ShowAsync();
        if (result != ContentDialogResult.None)
            await Local("scientific-execution", result == ContentDialogResult.Primary ? "enable" : "disable");
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
        var originalWorkspace = _boundWorkspace;
        _topology = default;
        await Execute(new { action = "topology", run = row.Id });
        if (_topology.ValueKind != JsonValueKind.Object) return;
        var nodes = _topology.GetProperty("nodes").EnumerateArray().Select(x => new TopologyNode(
            x.GetProperty("id").GetInt32(), x.GetProperty("kv").GetDouble(), x.GetProperty("active").GetBoolean())).ToArray();
        var links = _topology.GetProperty("links").EnumerateArray().Select(x => new TopologyLink(
            x.GetProperty("id").GetInt32(), x.GetProperty("from").GetInt32(), x.GetProperty("to").GetInt32(), x.GetProperty("type").GetString()!,
            x.GetProperty("closed").GetBoolean())).ToArray();
        var devices = _topology.GetProperty("devices").EnumerateArray().Select(x => new ModelParameter(
            x.GetProperty("element").GetString()!, x.GetProperty("index").GetInt32(), x.GetProperty("field").GetString()!,
            x.GetProperty("value").GetRawText(),
            x.TryGetProperty("minimum", out var minimum) ? minimum.GetDouble() : null,
            x.TryGetProperty("maximum", out var maximum) ? maximum.GetDouble() : null)).ToArray();
        var edit = await ShowTopology(nodes, links, devices);
        if (edit != null && !_busy && !WorkspaceChanged() && originalWorkspace == _boundWorkspace)
            await Execute(new { action = "save-model-revision", run = row.Id, edit });
        else if (edit != null) Notify("Workspace changed before the revision could be saved.", InfoBarSeverity.Warning);
    }
    private async void ModelRevisionDiff(object sender, RoutedEventArgs e)
    {
        if (!_busy && !WorkspaceChanged() && ModelRevisions.SelectedItem is Entry row && row.Info != null)
            await new ContentDialog { XamlRoot = Root.XamlRoot, Title = row.Label, Content = Text(row.Info), CloseButtonText = "Close" }.ShowAsync();
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
        RenderPlugins();
        await Execute(new { action = "plugins" });
        if (_pluginCatalog.ValueKind != JsonValueKind.Array) { RenderPlugins(); return; }
        RenderPlugins();
    }
    private async void RegisterNgspice(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var picker = await PickFile(".exe");
        if (picker != null)
        {
            await Execute(new { action = "local", command = "register-ngspice", args = new[] { picker } });
            if (!_operationError) await Execute(new { action = "plugins" });
        }
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
        if (picker != null)
        {
            await Execute(new { action = "local", command = "import-knowledge", args = new[] { picker } });
            if (!_operationError) await Execute(new { action = "knowledge-packs" });
        }
    }
    private async void Knowledge(object sender, RoutedEventArgs e) => await Execute(new { action = "knowledge-packs" });
    private async void OpenKnowledgePack(object sender, RoutedEventArgs e)
    {
        if (_busy || WorkspaceChanged() || KnowledgePacks.SelectedItem is not Entry pack) return;
        var workspace = _boundWorkspace;
        var offset = 0;
        while (!_busy && !WorkspaceChanged() && workspace == _boundWorkspace)
        {
            _knowledgePage = default;
            await Execute(new { action = "knowledge-pack", id = pack.Id, offset });
            if (_knowledgePage.ValueKind != JsonValueKind.Object) return;
            var page = _knowledgePage;
            var content = new StackPanel { Spacing = 16 };
            int total = page.GetProperty("total").GetInt32();
            content.Children.Add(ConversationMessageView.Metadata($"References {offset+1}–{Math.Min(offset+10,total)} of {total} · imported, not independently verified"));
            foreach (var reference in page.GetProperty("entries").EnumerateArray())
            {
                var section = new StackPanel { Spacing = 4 };
                var name = Text(reference.GetProperty("function").GetString()!, 15);
                name.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold;
                section.Children.Add(name);
                section.Children.Add(Text(reference.GetProperty("description").GetString()!, 14));
                section.Children.Add(ConversationMessageView.Metadata(reference.GetProperty("source").GetString() + " · " + reference.GetProperty("version").GetString()));
                content.Children.Add(section);
            }
            var dialog = new ContentDialog { XamlRoot = Root.XamlRoot, Title = pack.Label, CloseButtonText = "Close",
                Content = new ScrollViewer { Content = content, MaxHeight = 440, VerticalScrollBarVisibility = ScrollBarVisibility.Auto },
                PrimaryButtonText = offset + 10 < total ? "Next" : "", SecondaryButtonText = offset > 0 ? "Previous" : "" };
            var choice = await dialog.ShowAsync();
            if (choice == ContentDialogResult.Primary) offset += 10;
            else if (choice == ContentDialogResult.Secondary) offset = Math.Max(0, offset-10);
            else return;
        }
    }
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

