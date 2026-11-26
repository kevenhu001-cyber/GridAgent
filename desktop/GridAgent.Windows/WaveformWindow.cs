using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace GridAgent.Windows;

internal sealed record WaveformSeries(string Channel, double[] Time, double[] Value, int Samples,
                                      double Minimum, double Maximum);

internal sealed class WaveformWindow : Window
{
    private readonly ComboBox _channels;
    private readonly TextBlock _summary;
    private readonly WaveformPlot _plot;
    private readonly IReadOnlyList<WaveformSeries> _series;

    public WaveformWindow(IReadOnlyList<WaveformSeries> series)
    {
        _series = series;
        Title = "Voltage waveform — GridAgent";
        Width = 900;
        Height = 500;
        MinWidth = 500;
        MinHeight = 340;
        Background = Brushes.White;
        FontFamily = new FontFamily("Segoe UI");
        var layout = new DockPanel { Margin = new Thickness(24) };
        var header = new StackPanel { Orientation = Orientation.Horizontal };
        header.Children.Add(new TextBlock { Text = "Voltage waveform", FontSize = 20,
            FontWeight = FontWeights.SemiBold, Margin = new Thickness(0, 0, 24, 0) });
        _channels = new ComboBox { Width = 200, ItemsSource = series.Select(s => s.Channel).ToArray() };
        header.Children.Add(_channels);
        DockPanel.SetDock(header, Dock.Top);
        layout.Children.Add(header);
        _summary = new TextBlock { Foreground = Brushes.DimGray, Margin = new Thickness(0, 12, 0, 12) };
        DockPanel.SetDock(_summary, Dock.Top);
        layout.Children.Add(_summary);
        _plot = new WaveformPlot();
        layout.Children.Add(_plot);
        Content = layout;
        _channels.SelectionChanged += (_, _) => SelectChannel();
        if (series.Count > 0) _channels.SelectedIndex = 0;
    }

    private void SelectChannel()
    {
        if (_channels.SelectedIndex < 0) return;
        var data = _series[_channels.SelectedIndex];
        _summary.Text = $"{data.Channel} · {data.Samples} source samples · min {data.Minimum:G5} · max {data.Maximum:G5} p.u.";
        _plot.Series = data;
        _plot.InvalidateVisual();
    }
}

internal sealed class WaveformPlot : FrameworkElement
{
    public WaveformSeries? Series { get; set; }

    protected override void OnRender(DrawingContext dc)
    {
        base.OnRender(dc);
        if (Series is not { } s || s.Time.Length == 0 || ActualWidth < 150 || ActualHeight < 100) return;
        var area = new Rect(66, 10, ActualWidth - 85, ActualHeight - 48);
        double t0 = s.Time[0], t1 = s.Time[^1];
        double min = s.Minimum, max = s.Maximum;
        if (max == min) { min -= 0.05; max += 0.05; }
        double timeSpan = t1 > t0 ? t1 - t0 : 1.0;
        var grid = new Pen(new SolidColorBrush(Color.FromRgb(231, 231, 231)), 1);
        var axis = new Pen(Brushes.DimGray, 1);
        var trace = new Pen(new SolidColorBrush(Color.FromRgb(25, 80, 155)), 1.5);
        double dpi = VisualTreeHelper.GetDpi(this).PixelsPerDip;
        void Label(string text, double x, double y)
        {
            var label = new FormattedText(text, CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
                new Typeface("Segoe UI"), 11, Brushes.DimGray, dpi);
            dc.DrawText(label, new Point(x, y));
        }
        for (int i = 0; i <= 4; i++)
        {
            double frac = i / 4.0;
            double y = area.Top + frac * area.Height;
            double x = area.Left + frac * area.Width;
            dc.DrawLine(grid, new Point(area.Left, y), new Point(area.Right, y));
            dc.DrawLine(grid, new Point(x, area.Top), new Point(x, area.Bottom));
            Label((max - frac * (max - min)).ToString("G4", CultureInfo.InvariantCulture), 4, y - 7);
            Label((t0 + frac * timeSpan).ToString("G4", CultureInfo.InvariantCulture), x - 7, area.Bottom + 5);
        }
        dc.DrawLine(axis, area.TopLeft, area.BottomLeft);
        dc.DrawLine(axis, area.BottomLeft, area.BottomRight);
        Label("Time (s)", area.Left + area.Width / 2 - 15, area.Bottom + 22);
        var geometry = new StreamGeometry();
        using (var g = geometry.Open())
        {
            Point At(int i) => new(area.Left + (s.Time[i] - t0) / timeSpan * area.Width,
                area.Bottom - (s.Value[i] - min) / (max - min) * area.Height);
            g.BeginFigure(At(0), false, false);
            for (int i = 1; i < s.Time.Length; i++) g.LineTo(At(i), true, false);
        }
        geometry.Freeze();
        dc.DrawGeometry(null, trace, geometry);
    }
}
