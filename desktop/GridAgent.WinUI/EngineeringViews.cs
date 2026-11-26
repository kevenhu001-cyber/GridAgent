using System.Globalization;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using Microsoft.UI.Xaml.Automation;
using Windows.Foundation;

namespace GridAgent.Windows;

internal sealed record ChartTrace(string Name, double[] X, double[] Y);
internal sealed record ChartData(string Title, string XLabel, string YLabel, bool Scatter, ChartTrace[] Traces);
internal sealed record WaveformSeries(string Channel, double[] Time, double[] Value, int Samples, double Minimum, double Maximum);
internal sealed record TopologyNode(int Id, double Kv, bool Active);
internal sealed record TopologyLink(int From, int To, string Type, bool Closed);
internal sealed record ModelParameter(string Element, int Index, string Field, string Value)
{
    public string Label => $"{Element} {Index} · {Field} = {Value}";
}

public partial class MainWindow
{
    private readonly List<Window> _engineeringWindows = new();
    private void OpenEngineeringWindow(string title, FrameworkElement content, Action? cleanup = null)
    {
        var window = new Window { Title = title + " — GridAgent", Content = content };
        content.RequestedTheme = Root.RequestedTheme;
        window.AppWindow.Resize(new global::Windows.Graphics.SizeInt32(1000, 650));
        _engineeringWindows.Add(window);
        window.Closed += (_, _) => { cleanup?.Invoke(); _engineeringWindows.Remove(window); };
        window.Activate();
    }
    private static TextBlock Text(string value, double size = 14) =>
        new() { Text = value, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true, FontSize = size };
    private static Button ActionButton(string label, RoutedEventHandler handler)
    {
        var button = new Button { Content = label };
        button.Click += handler;
        return button;
    }
    private void FilterPlugins(object sender, TextChangedEventArgs e)
    {
        if (PluginRows != null) RenderPlugins();
    }
    private void RenderPlugins()
    {
        if (PluginRows == null) return;
        PluginRows.Children.Clear();
        if (_pluginCatalog.ValueKind != JsonValueKind.Array) return;
        var filter = PluginSearch?.Text.Trim() ?? "";
        foreach (var item in _pluginCatalog.EnumerateArray())
        {
            var id = item.GetProperty("id").GetString()!;
            var title = item.GetProperty("title").GetString()!;
            var installed = item.GetProperty("installed").GetBoolean();
            var managed = item.GetProperty("managed").GetBoolean();
            var requirements = string.Join(", ", item.GetProperty("requirements").EnumerateArray().Select(x => x.GetString()));
            var tools = string.Join(", ", item.GetProperty("tools").EnumerateArray().Select(x => x.GetString()));
            var versions = string.Join(", ", item.GetProperty("versions").EnumerateObject().Select(x => x.Name + " " + x.Value.GetString()));
            if (!(title + " " + id + " " + tools).Contains(filter, StringComparison.OrdinalIgnoreCase)) continue;
            var details = new StackPanel { Spacing = 8 };
            var name = Text(title, 18); name.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold;
            details.Children.Add(name);
            details.Children.Add(Text(installed ? "Available locally" : "Not installed"));
            details.Children.Add(Text("Capabilities: " + tools));
            var expander = new Expander { Header = "Dependencies and versions", HorizontalAlignment = HorizontalAlignment.Stretch, Content = Text(requirements + (versions.Length > 0 ? "\n" + versions : "")) };
            details.Children.Add(expander);
            var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
            void Add(string label, string command, bool enabled, string? question)
            {
                var button = ActionButton(label, async (_, _) =>
                {
                    if (_busy) { Notify("Another operation is running.", InfoBarSeverity.Warning); return; }
                    if (question != null && !await Confirm(label + " " + title, question)) return;
                    await Local(command, id);
                    var failed = _operationError;
                    await Execute(new { action = "plugins" });
                    if (failed) Notify("Plugin operation failed. See the assistant for details.", InfoBarSeverity.Error);
                    else if (!_operationError) Notify("Plugin operation completed. Review the refreshed catalog and conversation for results.");
                });
                button.IsEnabled = enabled;
                actions.Children.Add(button);
            }
            Add(managed ? "Uninstall" : installed ? "Available" : "Install",
                managed ? "plugin-remove" : "plugin-install", managed || !installed,
                managed ? "Remove the managed packages? Existing results are retained." :
                    "Download packages from PyPI? They execute under your local account. " + requirements);
            if (managed && installed)
            {
                Add("Check update", "plugin-check", true, null);
                Add("Update", "plugin-update", true, "Download and probe updated packages from PyPI?");
                Add("Rollback", "plugin-rollback", item.GetProperty("rollback_available").GetBoolean(), "Restore the previous plugin generation?");
            }
            details.Children.Add(actions);
            PluginRows.Children.Add(new Border { Padding = new Thickness(16), CornerRadius = new CornerRadius(8), BorderThickness = new Thickness(1), Style = (Style)Application.Current.Resources["EngineeringCardStyle"], Child = details });
        }
        if (PluginRows.Children.Count == 0) PluginRows.Children.Add(Text("No matching plugins."));
    }

    private void ShowWaveforms(IReadOnlyList<WaveformSeries> channels)
    {
        ShowCharts(channels.Select(s => new ChartData(
            $"{s.Channel} · {s.Samples} samples · min {s.Minimum:G5} · max {s.Maximum:G5}",
            "Time (s)", "Voltage (p.u.)", false, new[] { new ChartTrace(s.Channel, s.Time, s.Value) })).ToArray());
    }
    private void ShowCharts(ChartData[] charts)
    {
        if (charts.Length == 0) { Notify("No chart data available.", InfoBarSeverity.Warning); return; }
        var viewer = new ScientificPlotView(charts);
        OpenEngineeringWindow("Scientific results", viewer, viewer.Release);
    }
    private static Brush Ink(FrameworkElement element) => new SolidColorBrush(element.ActualTheme == ElementTheme.Dark ? Microsoft.UI.Colors.White : Microsoft.UI.Colors.Black);
    private static Brush SeriesColor(int index)
    {
        var colors = new[] { Microsoft.UI.Colors.DodgerBlue, Microsoft.UI.Colors.OrangeRed, Microsoft.UI.Colors.MediumSeaGreen, Microsoft.UI.Colors.MediumOrchid };
        return new SolidColorBrush(colors[index % colors.Length]);
    }
    private static void LineAt(Canvas canvas, double x1, double y1, double x2, double y2, Brush brush, double thickness = 1, bool dashed = false)
    {
        var line = new Line { X1 = x1, Y1 = y1, X2 = x2, Y2 = y2, Stroke = brush, StrokeThickness = thickness };
        if (dashed) line.StrokeDashArray = new DoubleCollection { 4, 3 };
        canvas.Children.Add(line);
    }
    private static void LabelAt(Canvas canvas, string label, double x, double y, Brush? brush = null)
    {
        var text = new TextBlock { Text = label, FontSize = 12 };
        if (brush != null) text.Foreground = brush;
        Canvas.SetLeft(text, x); Canvas.SetTop(text, y); canvas.Children.Add(text);
    }
    private async Task<object?> ShowTopology(TopologyNode[] nodes, TopologyLink[] links, ModelParameter[] devices)
    {
        // Use a separate native window for inspection and a modal confirmation for revision creation.
        var canvas = new Canvas { Width = 850, Height = 470 };
        var root = new StackPanel { Spacing = 10, Width = 850 };
        root.Children.Add(Text($"{nodes.Length} buses · {links.Length} branches. Open branches are dashed."));
        var scroll = new ScrollViewer { Content = canvas, ZoomMode = ZoomMode.Enabled, MinZoomFactor = 1, MaxZoomFactor = 5,
            HorizontalScrollMode = ScrollMode.Enabled, VerticalScrollMode = ScrollMode.Enabled, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
        root.Children.Add(scroll);
        void Draw()
        {
            canvas.Children.Clear();
            var ink = Ink(canvas);
            var positions = nodes.Select((n, i) => (n.Id, Point: new Point(425 + 330 * Math.Cos(2 * Math.PI * i / Math.Max(1, nodes.Length)), 235 + 180 * Math.Sin(2 * Math.PI * i / Math.Max(1, nodes.Length))))).ToDictionary(x => x.Id, x => x.Point);
            foreach (var link in links)
                if (positions.TryGetValue(link.From, out var a) && positions.TryGetValue(link.To, out var b))
                    LineAt(canvas, a.X, a.Y, b.X, b.Y, link.Type == "transformer" ? SeriesColor(0) : ink, 1.5, !link.Closed);
            foreach (var node in nodes)
            {
                var at = positions[node.Id];
                var circle = new Ellipse { Width = 13, Height = 13, Fill = node.Active ? SeriesColor(0) : new SolidColorBrush(Microsoft.UI.Colors.Gray), Stroke = ink, StrokeThickness = 1 };
                Canvas.SetLeft(circle, at.X - 6.5); Canvas.SetTop(circle, at.Y - 6.5); canvas.Children.Add(circle);
                LabelAt(canvas, $"Bus {node.Id} · {node.Kv:G4} kV", at.X + 8, at.Y - 10);
            }
        }
        canvas.Loaded += (_, _) => Draw();
        canvas.ActualThemeChanged += (_, _) => Draw();
        var picker = new ComboBox { Header = "Model parameter", ItemsSource = devices, DisplayMemberPath = "Label", HorizontalAlignment = HorizontalAlignment.Stretch };
        var value = new TextBox { Header = "New value" };
        var message = Text("");
        root.Children.Add(picker); root.Children.Add(value); root.Children.Add(message);
        picker.SelectionChanged += (_, _) => { if (picker.SelectedItem is ModelParameter parameter) value.Text = parameter.Value; };
        object? edit = null;
        var dialog = new ContentDialog { XamlRoot = Root.XamlRoot, Title = "Power network topology",
            Content = new ScrollViewer { Content = root, MaxHeight = 540, MaxWidth = 850 }, PrimaryButtonText = "Save new revision", CloseButtonText = "Close",
            DefaultButton = ContentDialogButton.Close, IsPrimaryButtonEnabled = devices.Length > 0 };
        dialog.PrimaryButtonClick += (_, args) =>
        {
            if (picker.SelectedItem is not ModelParameter parameter) { message.Text = "Select a model parameter."; args.Cancel = true; return; }
            object fieldValue;
            if (parameter.Field == "closed" && bool.TryParse(value.Text, out var closed)) fieldValue = closed;
            else if (parameter.Field != "closed" && double.TryParse(value.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var number) && double.IsFinite(number)) fieldValue = number;
            else { message.Text = parameter.Field == "closed" ? "Enter true or false." : "Enter a finite number."; args.Cancel = true; return; }
            edit = new { op = "edit", element = parameter.Element, index = parameter.Index, field = parameter.Field, value = fieldValue };
        };
        if (devices.Length > 0) picker.SelectedIndex = 0;
        return await dialog.ShowAsync() == ContentDialogResult.Primary ? edit : null;
    }
}
