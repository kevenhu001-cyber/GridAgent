using System.Globalization;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using Windows.Foundation;

namespace GridAgent.Windows;

// Inspection and parameter revision editor, not a live grid-control or schematic CAD surface.
internal sealed class TopologyInspector : Grid
{
    private readonly TopologyNode[] _nodes;
    private readonly TopologyLink[] _links;
    private readonly ModelParameter[] _devices;
    private readonly Canvas _diagram = new() { Background = new SolidColorBrush(Microsoft.UI.Colors.Transparent) };
    private readonly ComboBox _layout = new() { ItemsSource = new[] { "Voltage levels", "Circular" } };
    private readonly ComboBox _parameters = new() { DisplayMemberPath = "Label", HorizontalAlignment = HorizontalAlignment.Stretch };
    private readonly TextBox _search = new() { PlaceholderText = "Search parameter or device" };
    private readonly TextBox _value = new() { Header = "New value" };
    private readonly TextBlock _selection = new() { Text = "Select a bus or branch to inspect it.", TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true };
    private readonly TextBlock _bounds = new() { TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true };
    private readonly InfoBar _error = new() { Severity = InfoBarSeverity.Error, IsOpen = false };
    private readonly Button _save = new() { Content = "Create revision", IsEnabled = false };
    private TopologyLink? _selectedLink;
    private int? _selectedBus;
    private readonly ScrollViewer _viewport;
    public event Action<object>? SaveRequested;

    public TopologyInspector(TopologyNode[] nodes, TopologyLink[] links, ModelParameter[] devices)
    {
        _nodes = nodes; _links = links; _devices = devices;
        Padding = new Thickness(20); ColumnSpacing = 16; RowSpacing = 12;
        RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(300) });
        var header = new StackPanel { Spacing = 4 };
        header.Children.Add(new TextBlock { Text = "Network topology", FontSize = 24, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
        header.Children.Add(new TextBlock { Text = $"{nodes.Length} buses · {links.Length} branches · dashed lines indicate open branches", TextWrapping = TextWrapping.Wrap });
        SetColumnSpan(header, 2); Children.Add(header);
        var left = new Grid { RowSpacing = 8 };
        left.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        left.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        var toolbar = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        toolbar.Children.Add(_layout);
        var reset = new Button { Content = "Reset zoom" }; toolbar.Children.Add(reset);
        left.Children.Add(toolbar);
        _viewport = new ScrollViewer { Content = _diagram, ZoomMode = ZoomMode.Enabled, MinZoomFactor = 0.5f, MaxZoomFactor = 5,
            HorizontalScrollMode = ScrollMode.Enabled, VerticalScrollMode = ScrollMode.Enabled,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
        SetRow(_viewport, 1); left.Children.Add(_viewport); SetRow(left, 1); Children.Add(left);
        var inspector = new StackPanel { Spacing = 12 };
        inspector.Children.Add(new TextBlock { Text = "Inspector", FontSize = 20, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold });
        inspector.Children.Add(_selection);
        var all = new Button { Content = "Show all editable parameters" };
        inspector.Children.Add(all); inspector.Children.Add(_search);
        inspector.Children.Add(_parameters); inspector.Children.Add(_bounds); inspector.Children.Add(_value); inspector.Children.Add(_error); inspector.Children.Add(_save);
        _save.Style = (Style)Application.Current.Resources["AccentButtonStyle"];
        var scroll = new ScrollViewer { Content = inspector, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
        SetRow(scroll, 1); SetColumn(scroll, 1); Children.Add(scroll);
        AutomationProperties.SetName(_diagram, "Power network diagram");
        AutomationProperties.SetName(_parameters, "Editable model parameter");
        AutomationProperties.SetName(_search, "Search editable model parameters");
        _layout.SelectionChanged += (_, _) => Draw();
        _search.TextChanged += (_, _) => Filter();
        _parameters.SelectionChanged += (_, _) =>
        {
            _save.IsEnabled = _parameters.SelectedItem is ModelParameter;
            _error.IsOpen = false;
            if (_parameters.SelectedItem is ModelParameter parameter)
            {
                _value.Text = parameter.Value;
                _bounds.Text = parameter.Minimum is double min && parameter.Maximum is double max ?
                    $"Permitted range: {min:G6} – {max:G6}" : "Original value: " + parameter.Value;
            }
            else { _value.Text = ""; _bounds.Text = ""; }
        };
        _save.Click += (_, _) => Save();
        reset.Click += (_, _) => _viewport.ChangeView(0, 0, 1);
        all.Click += (_, _) => { _selectedLink = null; _selectedBus = null; _search.Text = ""; _selection.Text = "All editable parameters"; Filter(); Draw(); };
        _viewport.SizeChanged += (_, _) => Draw();
        ActualThemeChanged += (_, _) => Draw();
        Loaded += (_, _) => Draw();
        _layout.SelectedIndex = 0;
        Filter();
    }

    public void ShowError(string text) { _error.Message = text; _error.IsOpen = true; }

    private void Filter()
    {
        var query = _search.Text.Trim();
        var options = _devices.Where(d => (_selectedLink == null || (d.Element == _selectedLink.Type && d.Index == _selectedLink.Id)) &&
            d.Label.Contains(query, StringComparison.OrdinalIgnoreCase)).ToArray();
        _parameters.ItemsSource = options;
        _parameters.SelectedIndex = options.Length > 0 ? 0 : -1;
        _save.IsEnabled = options.Length > 0;
    }
    private void Save()
    {
        if (_parameters.SelectedItem is not ModelParameter p) return;
        object value;
        if (p.Field == "closed" && bool.TryParse(_value.Text, out var closed)) value = closed;
        else if (p.Field != "closed" && double.TryParse(_value.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var number) &&
                 double.IsFinite(number) && (p.Minimum is null || number >= p.Minimum) && (p.Maximum is null || number <= p.Maximum))
            value = number;
        else { ShowError(p.Field == "closed" ? "Enter true or false." : "Enter a finite number within the permitted range."); return; }
        SaveRequested?.Invoke(new { op = "edit", element = p.Element, index = p.Index, field = p.Field, value });
    }
    private void Draw()
    {
        if (_nodes.Length == 0 || _viewport.ActualWidth < 20) return;
        _diagram.Children.Clear();
        double width = Math.Max(540, _viewport.ActualWidth - 20);
        double height = Math.Max(400, _viewport.ActualHeight - 20);
        var positions = new Dictionary<int, Point>();
        if (_layout.SelectedIndex == 0)
        {
            var levels = _nodes.GroupBy(n => n.Kv).OrderByDescending(g => g.Key).ToArray();
            width = Math.Max(width, levels.Max(g => g.Count()) * 92 + 100);
            height = Math.Max(height, levels.Length * 100 + 80);
            for (int i = 0; i < levels.Length; i++)
            {
                var group = levels[i].OrderBy(n => n.Id).ToArray();
                for (int j = 0; j < group.Length; j++)
                    positions[group[j].Id] = new Point(55 + (width - 110) * (j + 0.5) / group.Length,
                        50 + (height - 100) * (i + 0.5) / levels.Length);
            }
        }
        else
        {
            width = Math.Max(width, _nodes.Length * 22);
            height = Math.Max(height, _nodes.Length * 16);
            for (int i = 0; i < _nodes.Length; i++)
            {
                double angle = 2 * Math.PI * i / _nodes.Length;
                positions[_nodes[i].Id] = new Point(width / 2 + (width / 2 - 55) * Math.Cos(angle),
                    height / 2 + (height / 2 - 45) * Math.Sin(angle));
            }
        }
        _diagram.Width = width; _diagram.Height = height;
        var ink = new SolidColorBrush(ActualTheme == ElementTheme.Dark ? Microsoft.UI.Colors.White : Microsoft.UI.Colors.Black);
        var accent = new SolidColorBrush(Microsoft.UI.Colors.DodgerBlue);
        var muted = new SolidColorBrush(Microsoft.UI.Colors.Gray);
        foreach (var link in _links)
        {
            if (!positions.TryGetValue(link.From, out var a) || !positions.TryGetValue(link.To, out var b)) continue;
            var color = link == _selectedLink ? accent : link.Type == "trafo" ? accent : ink;
            var line = new Line { X1 = a.X, Y1 = a.Y, X2 = b.X, Y2 = b.Y, Stroke = color, StrokeThickness = link == _selectedLink ? 3 : 1.5 };
            if (!link.Closed) line.StrokeDashArray = new DoubleCollection { 4, 3 };
            _diagram.Children.Add(line);
            var target = new Line { X1 = a.X, Y1 = a.Y, X2 = b.X, Y2 = b.Y, Stroke = new SolidColorBrush(Microsoft.UI.Colors.Transparent), StrokeThickness = 12 };
            ToolTipService.SetToolTip(target, $"{link.Type} {link.Id}: {link.From} → {link.To} · {(link.Closed ? "closed" : "open")}");
            target.PointerPressed += (_, e) =>
            {
                _selectedBus = null; _selectedLink = link;
                _selection.Text = $"{link.Type} {link.Id}\nBus {link.From} → {link.To}\n{(link.Closed ? "Closed" : "Open")}";
                _search.Text = ""; Filter(); Draw(); e.Handled = true;
            };
            _diagram.Children.Add(target);
        }
        foreach (var node in _nodes)
        {
            var at = positions[node.Id];
            var button = new Button { Content = node.Id.ToString(CultureInfo.InvariantCulture), Padding = new Thickness(5, 2, 5, 2), MinWidth = 36,
                BorderBrush = node.Id == _selectedBus ? accent : muted, BorderThickness = new Thickness(node.Id == _selectedBus ? 2 : 1),
                Opacity = node.Active ? 1 : 0.6 };
            Canvas.SetLeft(button, at.X - 18); Canvas.SetTop(button, at.Y - 14);
            AutomationProperties.SetName(button, $"Bus {node.Id}, {node.Kv:G4} kilovolts");
            ToolTipService.SetToolTip(button, $"{node.Kv:G4} kV · {(node.Active ? "in service" : "out of service")}");
            button.Click += (_, _) =>
            {
                _selectedBus = node.Id; _selectedLink = null;
                int incident = _links.Count(l => l.From == node.Id || l.To == node.Id);
                _selection.Text = $"Bus {node.Id}\n{node.Kv:G4} kV · {(node.Active ? "In service" : "Out of service")}\n{incident} connected branches";
                _search.Text = ""; Filter(); Draw();
            };
            _diagram.Children.Add(button);
        }
    }
}
