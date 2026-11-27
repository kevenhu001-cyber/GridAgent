using System.Globalization;
using System.Numerics;
using System.Text.Json;
using Microsoft.Graphics.Canvas.UI.Xaml;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Color = global::Windows.UI.Color;

namespace GridAgent.Windows;

// Data-only native views. Coordinates and dimensions have already been bounded by the engine.
internal sealed class ScientificDataView : Grid
{
    private readonly JsonElement _data;
    private readonly string _kind;
    private CanvasControl? _canvas;
    private ScrollViewer? _scroll;
    private double _angle = 45;

    public ScientificDataView(JsonElement data)
    {
        _data = data;
        _kind = data.GetProperty("kind").GetString()!;
        Padding = new Thickness(24);
        RowSpacing = 12;
        RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        var header = new StackPanel { Spacing = 6 };
        header.Children.Add(ScientificVisualStyle.Title(data.GetProperty("title").GetString()!));
        header.Children.Add(ConversationMessageView.Metadata("Unverified script output · Run " +
            data.GetProperty("run_id").GetString()![..8]));
        if (_kind is "heatmap" or "surface")
        {
            var x = Axis("x"); var y = Axis("y"); var z = Matrix();
            var values = z.SelectMany(row => row).ToArray();
            header.Children.Add(ConversationMessageView.Plain(
                $"{Label("x_label")}: {Format(x[0])} – {Format(x[^1])} · " +
                $"{Label("y_label")}: {Format(y[0])} – {Format(y[^1])} · " +
                $"{Label("value_label")}: {Format(values.Min())} – {Format(values.Max())}", 13));
            header.Children.Add(ConversationMessageView.Plain(_kind == "surface"
                ? "Orthographic wireframe · independently normalized axes; not a metric 3-D scale."
                : "Uniform sample grid · x increases right, y increases upward.", 12));
        }
        if (_kind == "topology")
            header.Children.Add(ConversationMessageView.Plain("Undirected layout · positions supplied by the model; not electrical validation.", 12));
        if (_kind == "surface")
        {
            var angle = new Slider { Header = "Rotate view (degrees)", Minimum = 0, Maximum = 360, Value = _angle };
            angle.ValueChanged += (_, args) => { _angle = args.NewValue; _canvas?.Invalidate(); };
            header.Children.Add(angle);
        }
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        header.Children.Add(actions);
        Children.Add(header);
        if (_kind == "table")
        {
            var copy = ScientificVisualStyle.Action("Copy table as tab-separated text", "\uE8C8");
            copy.Click += (_, _) => CopyTable();
            actions.Children.Add(copy);
            var scroller = Table();
            SetRow(scroller, 1); Children.Add(scroller);
            return;
        }

        _canvas = new CanvasControl { MinWidth = 320, MinHeight = 240 };
        _canvas.Draw += Draw;
        var reset = ScientificVisualStyle.Action("Reset zoom", "\uE72C");
        reset.Click += (_, _) => _scroll?.ChangeView(0, 0, 1);
        actions.Children.Add(reset);
        AutomationProperties.SetName(_canvas, Label("title") + " " + _kind + "; values and ranges described above");
        _scroll = new ScrollViewer { Content = _canvas, ZoomMode = ZoomMode.Enabled,
            MinZoomFactor = 1, MaxZoomFactor = 5,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            HorizontalScrollMode = ScrollMode.Enabled, VerticalScrollMode = ScrollMode.Enabled };
        _scroll.SizeChanged += (_, _) =>
        {
            if (_canvas == null || _scroll == null) return;
            _canvas.Width = Math.Max(320, _scroll.ActualWidth - 18);
            _canvas.Height = Math.Max(240, _scroll.ActualHeight - 18);
        };
        ActualThemeChanged += (_, _) => _canvas?.Invalidate();
        SetRow(_scroll, 1); Children.Add(_scroll);
    }

    private string Label(string key) => _data.GetProperty(key).GetString()!;
    private static string Format(double value) => value.ToString("G6", CultureInfo.InvariantCulture);
    private double[] Axis(string key) => _data.GetProperty(key).EnumerateArray().Select(v => v.GetDouble()).ToArray();
    private double[][] Matrix() => _data.GetProperty("z").EnumerateArray()
        .Select(row => row.EnumerateArray().Select(v => v.GetDouble()).ToArray()).ToArray();
    private static double Normalize(double v, double lo, double hi) => hi == lo ? 0.5 : (v - lo) / (hi - lo);
    private static Color FieldColor(double fraction)
    {
        double t = Math.Clamp(fraction, 0, 1);
        // Blue to amber sequential ramp, independent of application theme.
        return Color.FromArgb(255, (byte)(30 + 220*t), (byte)(65 + 125*t), (byte)(165 - 130*t));
    }

    private void CopyTable()
    {
        var columns = _data.GetProperty("columns").EnumerateArray().Select(v => v.GetString()!);
        // Treat string cells as literal text when pasted into a spreadsheet; preserve numeric cells.
        static string Safe(string value) => value.Length > 0 && "=+-@\t\r".Contains(value[0]) ? "'" + value : value;
        var lines = new List<string> { string.Join("\t", columns.Select(Safe)) };
        foreach (var row in _data.GetProperty("rows").EnumerateArray())
            lines.Add(string.Join("\t", row.EnumerateArray().Select(v => v.ValueKind switch
            {
                JsonValueKind.String => Safe(v.GetString()!),
                JsonValueKind.Null => "",
                _ => v.GetRawText()
            })));
        ConversationMessageView.Copy(string.Join("\n", lines));
    }

    private ScrollViewer Table()
    {
        var grid = new Grid { RowSpacing = 8, ColumnSpacing = 24, Padding = new Thickness(8) };
        var columns = _data.GetProperty("columns").EnumerateArray().Select(v => v.GetString()!).ToArray();
        foreach (var _ in columns) grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        void AddRow(string[] values, bool heading)
        {
            int row = grid.RowDefinitions.Count;
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            for (int i = 0; i < values.Length; i++)
            {
                var text = ConversationMessageView.Plain(values[i], 13);
                text.MinWidth = 80; text.MaxWidth = 240;
                if (heading) text.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold;
                else if (double.TryParse(values[i], NumberStyles.Float, CultureInfo.InvariantCulture, out _)) text.TextAlignment = TextAlignment.Right;
                SetRow(text, row); SetColumn(text, i); grid.Children.Add(text);
            }
        }
        AddRow(columns, true);
        foreach (var row in _data.GetProperty("rows").EnumerateArray())
            AddRow(row.EnumerateArray().Select(v => v.ValueKind switch
            {
                JsonValueKind.String => v.GetString()!,
                JsonValueKind.Null => "—",
                _ => v.GetRawText()
            }).ToArray(), false);
        return new ScrollViewer { Content = grid, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollMode = ScrollMode.Enabled };
    }

    private void Draw(CanvasControl sender, CanvasDrawEventArgs args)
    {
        var ds = args.DrawingSession;
        float width = (float)sender.ActualWidth, height = (float)sender.ActualHeight;
        if (width < 100 || height < 100) return;
        var ink = ScientificVisualStyle.Ink(ActualTheme);
        if (_kind == "topology")
        {
            var positions = new Dictionary<string, Vector2>();
            var nodes = _data.GetProperty("nodes");
            foreach (var node in nodes.EnumerateArray())
                positions[node.GetProperty("id").GetString()!] = new Vector2(
                    28 + (float)node.GetProperty("x").GetDouble()*(width-56),
                    28 + (1-(float)node.GetProperty("y").GetDouble())*(height-56));
            foreach (var edge in _data.GetProperty("edges").EnumerateArray())
                ds.DrawLine(positions[edge.GetProperty("source").GetString()!],
                    positions[edge.GetProperty("target").GetString()!], ink, 1);
            foreach (var node in nodes.EnumerateArray())
            {
                var point = positions[node.GetProperty("id").GetString()!];
                ds.FillCircle(point, 4, ScientificVisualStyle.Series(ActualTheme, 0));
                ds.DrawText(node.GetProperty("label").GetString()!, point.X + 6, point.Y - 17, ink);
            }
            return;
        }

        var z = Matrix();
        var values = z.SelectMany(row => row).ToArray();
        double lo = values.Min(), hi = values.Max();
        int nx = z[0].Length, ny = z.Length;
        if (_kind == "heatmap")
        {
            float left = 76, top = 24, w = width-164, h = height-88;
            if (w <= 0 || h <= 0) return;
            float dx = w/nx, dy = h/ny;
            for (int j = 0; j < ny; j++)
                for (int i = 0; i < nx; i++)
                    ds.FillRectangle(left+i*dx, top+(ny-1-j)*dy, dx, dy, FieldColor(Normalize(z[j][i], lo, hi)));
            for (int i = 0; i < 64; i++)
                ds.FillRectangle(left+w+12, top+i*h/64, 15, h/64+0.2f, FieldColor(1-i/63.0));
            ds.DrawText(Format(hi), left+w+30, top, ink);
            ds.DrawText(Format(lo), left+w+30, top+h-18, ink);
            var x = Axis("x"); var y = Axis("y");
            ds.DrawText(Format(x[0]), left, top+h+2, ink);
            ds.DrawText(Format(x[^1]), left+w-44, top+h+2, ink);
            ds.DrawText(Label("x_label"), left+w/2-30, top+h+24, ink);
            ds.DrawText(Format(y[0]), 2, top+h-18, ink);
            ds.DrawText(Format(y[^1]), 2, top, ink);
            ds.DrawText(Label("y_label"), 2, 0, ink);
            return;
        }

        // Orthographic projection of an independently normalized regular grid.
        double radians = _angle*Math.PI/180, cos = Math.Cos(radians), sin = Math.Sin(radians);
        float scale = Math.Min(width, height)*0.35f;
        Vector2 Project(int i, int j)
        {
            double x = 2.0*i/(nx-1)-1, y = 2.0*j/(ny-1)-1;
            double a = x*cos-y*sin, b = x*sin+y*cos;
            double v = Normalize(z[j][i], lo, hi)-0.5;
            return new Vector2(width/2+(float)a*scale, height/2+(float)(0.5*b-v)*scale);
        }
        for (int j = 0; j < ny; j++)
            for (int i = 0; i < nx; i++)
            {
                var p = Project(i, j);
                var color = FieldColor(Normalize(z[j][i], lo, hi));
                if (i+1 < nx) ds.DrawLine(p, Project(i+1, j), color, 1);
                if (j+1 < ny) ds.DrawLine(p, Project(i, j+1), color, 1);
            }
        ds.DrawText(Label("x_label") + " / " + Label("y_label") + " / " + Label("value_label"), 10, 10, ink);
    }

    public void Release()
    {
        if (_canvas == null) return;
        _canvas.Draw -= Draw;
        _canvas.RemoveFromVisualTree();
        _canvas = null;
    }
}
