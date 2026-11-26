using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace GridAgent.Windows;

internal sealed record ChartTrace(string Name, double[] X, double[] Y);
internal sealed record ChartData(string Title, string XLabel, string YLabel, bool Scatter, ChartTrace[] Traces);

internal sealed class ScientificChartWindow : Window
{
    public ScientificChartWindow(ChartData[] charts)
    {
        Title = "Scientific charts";
        Width = 900;
        Height = 540;
        MinWidth = 520;
        MinHeight = 380;
        var tabs = new TabControl { Margin = new Thickness(12) };
        foreach (var chart in charts)
        {
            var view = new DockPanel { Margin = new Thickness(10) };
            var legend = new WrapPanel { Margin = new Thickness(52, 0, 0, 8) };
            for (var index = 0; index < chart.Traces.Length; index++)
                legend.Children.Add(new TextBlock { Text = chart.Traces[index].Name,
                    Foreground = ScientificPlot.TraceColor(index), Margin = new Thickness(0, 0, 16, 0) });
            DockPanel.SetDock(legend, Dock.Top);
            view.Children.Add(legend);
            view.Children.Add(new ScientificPlot(chart));
            tabs.Items.Add(new TabItem { Header = chart.Title, Content = view });
        }
        Content = tabs;
    }
}

internal sealed class ScientificPlot(ChartData chart) : FrameworkElement
{
    private static readonly Brush[] Palette = [Brushes.SteelBlue, Brushes.DarkOrange, Brushes.SeaGreen, Brushes.MediumVioletRed];
    internal static Brush TraceColor(int index) => Palette[index % Palette.Length];

    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc);
        if (ActualWidth < 165 || ActualHeight < 110 || chart.Traces.Length == 0) return;
        var area = new Rect(85, 20, ActualWidth - 108, ActualHeight - 65);
        var xValues = chart.Traces.SelectMany(t => t.X).ToArray();
        var yValues = chart.Traces.SelectMany(t => t.Y).ToArray();
        if (xValues.Length == 0 || yValues.Length == 0) return;
        var x0 = xValues.Min();
        var x1 = xValues.Max();
        var y0 = yValues.Min();
        var y1 = yValues.Max();
        if (x0 == x1) { x0 -= 1; x1 += 1; }
        if (y0 == y1) { y0 -= 1; y1 += 1; }
        var dpi = VisualTreeHelper.GetDpi(this).PixelsPerDip;
        void Label(string label, double x, double y)
        {
            var text = new FormattedText(label, CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
                new Typeface("Segoe UI"), 11, Brushes.DimGray, dpi);
            dc.DrawText(text, new Point(x, y));
        }
        Point Map(double x, double y) => new(area.Left + area.Width * (x - x0) / (x1 - x0),
            area.Bottom - area.Height * (y - y0) / (y1 - y0));
        var grid = new Pen(Brushes.LightGray, 1);
        for (var idx = 0; idx < 5; idx++)
        {
            var t = idx / 4.0;
            var x = x0 + (x1 - x0) * t;
            var y = y0 + (y1 - y0) * t;
            var point = Map(x, y);
            dc.DrawLine(grid, new Point(point.X, area.Top), new Point(point.X, area.Bottom));
            dc.DrawLine(grid, new Point(area.Left, point.Y), new Point(area.Right, point.Y));
            Label(x.ToString("G4", CultureInfo.InvariantCulture), point.X - 8, area.Bottom + 5);
            Label(y.ToString("G4", CultureInfo.InvariantCulture), 15, point.Y - 7);
        }
        Label(chart.YLabel, 4, 0);
        Label(chart.XLabel, area.Left + area.Width / 2 - 30, area.Bottom + 26);
        dc.PushClip(new RectangleGeometry(area));
        for (var index = 0; index < chart.Traces.Length; index++)
        {
            var trace = chart.Traces[index];
            var brush = TraceColor(index);
            var pen = new Pen(brush, 1.5);
            for (var sample = 0; sample < Math.Min(trace.X.Length, trace.Y.Length); sample++)
            {
                var point = Map(trace.X[sample], trace.Y[sample]);
                if (chart.Scatter) dc.DrawEllipse(brush, null, point, 2.4, 2.4);
                else if (sample > 0) dc.DrawLine(pen, Map(trace.X[sample - 1], trace.Y[sample - 1]), point);
            }
        }
        dc.Pop();
    }
}
