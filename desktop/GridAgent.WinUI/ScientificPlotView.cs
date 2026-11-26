using System.Globalization;
using System.Numerics;
using System.Text;
using Microsoft.Graphics.Canvas.Geometry;
using Microsoft.Graphics.Canvas.Text;
using Microsoft.Graphics.Canvas.UI.Xaml;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Foundation;
using Color = global::Windows.UI.Color;

namespace GridAgent.Windows;

// One native Direct2D drawing surface instead of one XAML visual per sample.
internal sealed class ScientificPlotView : Grid
{
    private static readonly Color[] Palette =
    {
        Microsoft.UI.Colors.DodgerBlue, Microsoft.UI.Colors.OrangeRed, Microsoft.UI.Colors.MediumSeaGreen,
        Microsoft.UI.Colors.MediumOrchid, Microsoft.UI.Colors.Goldenrod, Microsoft.UI.Colors.Teal
    };
    private readonly ChartData[] _charts;
    private readonly CanvasControl _canvas = new() { MinWidth = 300, MinHeight = 220 };
    private readonly ComboBox _selector;
    private readonly TextBlock _summary = new() { TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true };
    private readonly TextBlock _cursor = new() { TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true, FontSize = 13 };
    private readonly StackPanel _legend = new() { Spacing = 4 };
    private readonly ScrollViewer _scroll;
    private TraceData[] _traces = Array.Empty<TraceData>();
    private ChartData? _chart;
    private double _xmin, _xmax, _ymin, _ymax;
    private double? _pointerX;
    private long _lastPointer;
    private const float Left = 76, Right = 24, Top = 20, Bottom = 66;
    private bool _released;

    private sealed class TraceData
    {
        public ChartTrace Source { get; }
        public (double X, double Y)[] Samples { get; }
        public (double X, double Y)[] Sorted { get; }
        public bool Visible { get; set; } = true;
        public TraceData(ChartTrace source)
        {
            Source = source;
            Samples = source.X.Zip(source.Y).Select(v => (v.First, v.Second)).ToArray();
            Sorted = Samples.Where(v => double.IsFinite(v.X) && double.IsFinite(v.Y)).OrderBy(v => v.X).ToArray();
        }
        public (double X, double Y)? Nearest(double x)
        {
            if (Sorted.Length == 0) return null;
            int lo = 0, hi = Sorted.Length;
            while (lo < hi)
            {
                int mid = lo + (hi - lo) / 2;
                if (Sorted[mid].X < x) lo = mid + 1; else hi = mid;
            }
            if (lo == 0) return Sorted[0];
            if (lo == Sorted.Length) return Sorted[^1];
            return x - Sorted[lo - 1].X <= Sorted[lo].X - x ? Sorted[lo - 1] : Sorted[lo];
        }
    }

    public ScientificPlotView(ChartData[] charts)
    {
        _charts = charts;
        Padding = new Thickness(24); RowSpacing = 12;
        RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        _selector = new ComboBox { ItemsSource = charts.Select(c => c.Title).ToArray(), Header = "Scientific chart", HorizontalAlignment = HorizontalAlignment.Stretch };
        Children.Add(_selector);
        var panel = new StackPanel { Spacing = 6 };
        panel.Children.Add(_summary); panel.Children.Add(_cursor);
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        var reset = new Button { Content = "Reset zoom" };
        var copy = new Button { Content = "Copy plotted CSV" };
        actions.Children.Add(reset); actions.Children.Add(copy);
        panel.Children.Add(actions);
        var legendExpander = new Expander { Header = "Series visibility", Content = new ScrollViewer { Content = _legend, MaxHeight = 140 }, IsExpanded = false };
        panel.Children.Add(legendExpander);
        SetRow(panel, 1); Children.Add(panel);
        _scroll = new ScrollViewer { Content = _canvas, ZoomMode = ZoomMode.Enabled, MinZoomFactor = 1, MaxZoomFactor = 8,
            HorizontalScrollMode = ScrollMode.Enabled, VerticalScrollMode = ScrollMode.Enabled,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
        SetRow(_scroll, 2); Children.Add(_scroll);
        AutomationProperties.SetName(_canvas, "Scientific plot; ranges, series and cursor values are available as text");
        _canvas.Draw += Draw;
        _canvas.PointerMoved += (_, e) =>
        {
            long now = Environment.TickCount64;
            if (now - _lastPointer < 33) return;
            _lastPointer = now;
            var pos = e.GetCurrentPoint(_canvas).Position;
            var width = _canvas.ActualWidth - Left - Right;
            if (_chart == null || width <= 0 || pos.X < Left || pos.X > Left + width) return;
            _pointerX = pos.X;
            var x = _xmin + (_xmax - _xmin) * (pos.X - Left) / width;
            _cursor.Text = string.Join("  ·  ", _traces.Where(t => t.Visible).Select(t =>
                t.Nearest(x) is { } s ? $"{t.Source.Name}: {s.X:G6}, {s.Y:G6}" : "").Where(s => s.Length > 0));
            _canvas.Invalidate();
        };
        _canvas.PointerExited += (_, _) => { _pointerX = null; _canvas.Invalidate(); };
        _scroll.SizeChanged += (_, _) =>
        {
            _canvas.Width = Math.Max(300, _scroll.ActualWidth - 18);
            _canvas.Height = Math.Max(220, _scroll.ActualHeight - 18);
        };
        ActualThemeChanged += (_, _) => _canvas.Invalidate();
        reset.Click += (_, _) => _scroll.ChangeView(0, 0, 1);
        copy.Click += (_, _) => CopyCsv();
        _selector.SelectionChanged += (_, _) => SelectChart();
        _selector.SelectedIndex = 0;
    }

    private void SelectChart()
    {
        if (_selector.SelectedIndex < 0) return;
        _chart = _charts[_selector.SelectedIndex];
        _traces = _chart.Traces.Select(t => new TraceData(t)).ToArray();
        _legend.Children.Clear();
        for (int i = 0; i < _traces.Length; i++)
        {
            var trace = _traces[i];
            var check = new CheckBox { Content = trace.Source.Name, IsChecked = true, Foreground = new SolidColorBrush(Palette[i % Palette.Length]) };
            check.Checked += (_, _) => { trace.Visible = true; UpdateBounds(); };
            check.Unchecked += (_, _) => { trace.Visible = false; UpdateBounds(); };
            _legend.Children.Add(check);
        }
        _pointerX = null;
        UpdateBounds();
        _cursor.Text = "Move the pointer over the plot to inspect nearby samples.";
    }

    private void UpdateBounds()
    {
        bool any = false;
        _xmin = _ymin = double.PositiveInfinity; _xmax = _ymax = double.NegativeInfinity;
        foreach (var trace in _traces.Where(t => t.Visible))
            foreach (var (x, y) in trace.Sorted)
            {
                any = true; _xmin = Math.Min(_xmin, x); _xmax = Math.Max(_xmax, x);
                _ymin = Math.Min(_ymin, y); _ymax = Math.Max(_ymax, y);
            }
        if (!any) { _xmin = _ymin = 0; _xmax = _ymax = 1; }
        if (_xmin == _xmax) { _xmin -= 1; _xmax += 1; }
        if (_ymin == _ymax) { _ymin -= 1; _ymax += 1; }
        _summary.Text = any && _chart != null ?
            $"{_chart.XLabel}: {_xmin:G5} – {_xmax:G5}   ·   {_chart.YLabel}: {_ymin:G5} – {_ymax:G5}" :
            "No visible finite data.";
        _canvas.Invalidate();
    }

    private void Draw(CanvasControl sender, CanvasDrawEventArgs args)
    {
        if (_released || _chart == null) return;
        float w = (float)sender.ActualWidth - Left - Right, h = (float)sender.ActualHeight - Top - Bottom;
        if (w <= 0 || h <= 0) return;
        var ds = args.DrawingSession;
        var dark = ActualTheme == ElementTheme.Dark;
        var ink = dark ? Microsoft.UI.Colors.White : Microsoft.UI.Colors.Black;
        var grid = Color.FromArgb(65, 128, 128, 128);
        using var format = new CanvasTextFormat { FontFamily = "Segoe UI", FontSize = 11 };
        for (int i = 0; i <= 5; i++)
        {
            float x = Left + i * w / 5, y = Top + i * h / 5;
            ds.DrawLine(x, Top, x, Top + h, grid);
            ds.DrawLine(Left, y, Left + w, y, grid);
            ds.DrawText((_xmin + i * (_xmax - _xmin) / 5).ToString("G4", CultureInfo.InvariantCulture), x - 12, Top + h + 5, ink, format);
            ds.DrawText((_ymax - i * (_ymax - _ymin) / 5).ToString("G4", CultureInfo.InvariantCulture), 2, y - 8, ink, format);
        }
        ds.DrawLine(Left, Top, Left, Top + h, ink);
        ds.DrawLine(Left, Top + h, Left + w, Top + h, ink);
        ds.DrawText(_chart.XLabel, Left + w / 2 - 30, Top + h + 30, ink, format);
        ds.DrawText(_chart.YLabel, 2, 0, ink, format);
        Vector2 Map(double x, double y) => new(Left + (float)((x - _xmin) / (_xmax - _xmin)) * w,
            Top + (float)((_ymax - y) / (_ymax - _ymin)) * h);
        for (int i = 0; i < _traces.Length; i++)
        {
            var trace = _traces[i];
            if (!trace.Visible) continue;
            var color = Palette[i % Palette.Length];
            if (_chart.Scatter)
            {
                foreach (var (x, y) in trace.Sorted) ds.FillCircle(Map(x, y), 2.4f, color);
                continue;
            }
            using var path = new CanvasPathBuilder(sender);
            bool started = false;
            foreach (var (x, y) in trace.Samples)
            {
                if (!double.IsFinite(x) || !double.IsFinite(y))
                {
                    if (started) path.EndFigure(CanvasFigureLoop.Open);
                    started = false; continue;
                }
                var point = Map(x, y);
                if (!started) { path.BeginFigure(point); started = true; }
                else path.AddLine(point);
            }
            if (started) path.EndFigure(CanvasFigureLoop.Open);
            using var geometry = CanvasGeometry.CreatePath(path);
            ds.DrawGeometry(geometry, color, 1.7f);
        }
        if (_pointerX is double px && px >= Left && px <= Left + w)
            ds.DrawLine((float)px, Top, (float)px, Top + h, ink, 0.7f);
    }

    private void CopyCsv()
    {
        var csv = new StringBuilder("series,x,y\n");
        foreach (var trace in _traces.Where(t => t.Visible))
            foreach (var (x, y) in trace.Samples)
                csv.Append('"').Append(trace.Source.Name.Replace("\"", "\"\"")).Append("\",")
                    .Append(x.ToString("R", CultureInfo.InvariantCulture)).Append(',')
                    .Append(y.ToString("R", CultureInfo.InvariantCulture)).Append('\n');
        ConversationMessageView.Copy(csv.ToString());
    }

    public void Release()
    {
        _released = true;
        _canvas.Draw -= Draw;
        _canvas.RemoveFromVisualTree();
        _scroll.Content = null;
    }
}
