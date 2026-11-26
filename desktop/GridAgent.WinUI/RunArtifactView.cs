using System.Globalization;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using Windows.Foundation;

namespace GridAgent.Windows;

internal static class RunArtifactView
{
    public static UIElement Create(ConversationMessage message)
    {
        var artifact = message.Artifact!;
        var panel = new StackPanel { Spacing = 10 };
        panel.Children.Add(new TextBlock { Text = artifact.Operation.Replace('_', ' '), FontSize = 18,
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold, TextWrapping = TextWrapping.Wrap });
        panel.Children.Add(ConversationMessageView.Plain($"{artifact.Backend} · {artifact.Case} · solver: {artifact.Status}", 13));
        panel.Children.Add(ConversationMessageView.Plain(artifact.Quality is { } q
            ? $"Local checks: {q.Passed}/{q.Total} · {q.Protocol}"
            : "Independent quality checks not recorded.", 13));
        if (artifact.Metrics.Length > 0)
        {
            var metrics = new Grid { ColumnSpacing = 12, RowSpacing = 6 };
            metrics.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            metrics.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            foreach (var metric in artifact.Metrics)
            {
                int row = metrics.RowDefinitions.Count;
                metrics.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                var key = ConversationMessageView.Plain(metric.Name.Replace('_', ' '), 13);
                var val = ConversationMessageView.Plain(metric.Value.ToString("G6", CultureInfo.InvariantCulture), 13);
                Grid.SetRow(key, row); Grid.SetRow(val, row); Grid.SetColumn(val, 1);
                metrics.Children.Add(key); metrics.Children.Add(val);
            }
            panel.Children.Add(new Expander { Header = "Numerical metrics", Content = metrics, IsExpanded = false,
                HorizontalAlignment = HorizontalAlignment.Stretch });
        }
        if (message.Preview is RunPreview preview) panel.Children.Add(Preview(preview));
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        if (artifact.HasPreview && message.Preview == null)
        {
            var previewButton = new Button { Content = "Preview chart" };
            previewButton.Click += (_, _) => message.RequestPreview?.Invoke(artifact.Id);
            actions.Children.Add(previewButton);
        }
        var open = new Button { Content = "Open simulation result" };
        open.Click += (_, _) => message.OpenRun?.Invoke(artifact.Id);
        actions.Children.Add(open); panel.Children.Add(actions);
        panel.Children.Add(ConversationMessageView.Plain("Run " + artifact.Id[..8], 12));
        return new Border { Style = (Style)Application.Current.Resources["EngineeringCardStyle"], Padding = new Thickness(16),
            BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(12), Child = panel };
    }

    private static UIElement Preview(RunPreview data)
    {
        var panel = new StackPanel { Spacing = 6 };
        panel.Children.Add(ConversationMessageView.Plain(data.Title, 14));
        var canvas = new Canvas { Height = 170 };
        AutomationProperties.SetName(canvas, $"{data.Title}; {data.XLabel}, {data.YLabel}");
        void Draw()
        {
            canvas.Children.Clear();
            double w = canvas.ActualWidth - 24, h = canvas.Height - 20;
            if (w < 20 || h < 20) return;
            double xmin = data.X.Min(), xmax = data.X.Max(), ymin = data.Y.Min(), ymax = data.Y.Max();
            double dx = xmax == xmin ? 1 : xmax - xmin, dy = ymax == ymin ? 1 : ymax - ymin;
            if (!double.IsFinite(dx) || !double.IsFinite(dy)) return;
            var brush = new SolidColorBrush(canvas.ActualTheme == ElementTheme.Dark ? Microsoft.UI.Colors.LightSkyBlue : Microsoft.UI.Colors.RoyalBlue);
            Point Map(int i) => new(12 + (data.X[i] - xmin) / dx * w, 10 + (ymax - data.Y[i]) / dy * h);
            var axis = new Line { X1 = 12, X2 = w + 12, Y1 = h + 10, Y2 = h + 10, Stroke = new SolidColorBrush(Microsoft.UI.Colors.Gray) };
            canvas.Children.Add(axis);
            if (data.Scatter)
            {
                var geometry = new GeometryGroup();
                for (int i = 0; i < data.X.Length; i++) geometry.Children.Add(new EllipseGeometry { Center = Map(i), RadiusX = 2, RadiusY = 2 });
                canvas.Children.Add(new Microsoft.UI.Xaml.Shapes.Path { Data = geometry, Fill = brush });
            }
            else
            {
                var points = new PointCollection();
                for (int i = 0; i < data.X.Length; i++) points.Add(Map(i));
                canvas.Children.Add(new Polyline { Points = points, Stroke = brush, StrokeThickness = 1.7 });
            }
        }
        canvas.SizeChanged += (_, _) => Draw(); canvas.ActualThemeChanged += (_, _) => Draw();
        panel.Children.Add(canvas);
        panel.Children.Add(ConversationMessageView.Plain($"{data.XLabel}: {data.X.Min():G5} – {data.X.Max():G5} · {data.YLabel}: {data.Y.Min():G5} – {data.Y.Max():G5}", 12));
        panel.Children.Add(ConversationMessageView.Plain($"Preview: {data.X.Length} of {data.SourcePoints} source points. Open the result for full inspection.", 12));
        return panel;
    }
}
