using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace GridAgent.Windows;

internal sealed record TopologyNode(int Id, double Kv, bool Active);
internal sealed record TopologyLink(int From, int To, string Type, bool Closed);
internal sealed record ModelParameter(string Element, int Index, string Field, string Value)
{
    public string Label => $"{Element} {Index} · {Field} = {Value}";
}

internal sealed class TopologyWindow : Window
{
    public object? Edit { get; private set; }

    public TopologyWindow(TopologyNode[] nodes, TopologyLink[] links, ModelParameter[] devices)
    {
        Title = "Power network topology";
        Width = 990;
        Height = 600;
        MinWidth = 650;
        MinHeight = 420;
        var root = new DockPanel { Margin = new Thickness(15) };
        var edits = new WrapPanel { Margin = new Thickness(0, 0, 0, 8) };
        DockPanel.SetDock(edits, Dock.Top);
        root.Children.Add(edits);
        var picker = new ComboBox { Width = 300, ItemsSource = devices, DisplayMemberPath = "Label", Margin = new Thickness(0, 0, 8, 0) };
        var value = new TextBox { Width = 110, Margin = new Thickness(0, 0, 8, 0) };
        var save = new Button { Content = "Save new model revision", IsEnabled = false };
        edits.Children.Add(picker);
        edits.Children.Add(value);
        edits.Children.Add(save);
        var error = new TextBlock { Foreground = Brushes.Firebrick };
        DockPanel.SetDock(error, Dock.Bottom);
        root.Children.Add(error);
        picker.SelectionChanged += (_, _) =>
        {
            if (picker.SelectedItem is not ModelParameter parameter) return;
            value.Text = parameter.Value;
            save.IsEnabled = true;
        };
        save.Click += (_, _) =>
        {
            if (picker.SelectedItem is not ModelParameter parameter) return;
            object fieldValue;
            if (parameter.Field == "closed" && bool.TryParse(value.Text, out var closed)) fieldValue = closed;
            else if (parameter.Field != "closed" &&
                double.TryParse(value.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out var number) &&
                double.IsFinite(number)) fieldValue = number;
            else
            {
                error.Text = parameter.Field == "closed" ? "Enter true or false." : "Enter a finite number.";
                return;
            }
            Edit = new { op = "edit", element = parameter.Element, index = parameter.Index, field = parameter.Field, value = fieldValue };
            DialogResult = true;
        };
        var canvas = Draw(nodes, links);
        var zoom = new ScaleTransform(1, 1);
        canvas.LayoutTransform = zoom;
        var scroll = new ScrollViewer { Content = canvas, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Background = Brushes.WhiteSmoke };
        scroll.PreviewMouseWheel += (_, e) =>
        {
            if ((System.Windows.Input.Keyboard.Modifiers & System.Windows.Input.ModifierKeys.Control) == 0) return;
            zoom.ScaleX = zoom.ScaleY = Math.Clamp(zoom.ScaleX * (e.Delta > 0 ? 1.15 : 1 / 1.15), 0.3, 3);
            e.Handled = true;
        };
        var hint = new TextBlock { Text = "Ctrl + wheel to zoom  ·  dashed branches are open  ·  blue branches are transformers",
            Margin = new Thickness(0, 0, 0, 6) };
        DockPanel.SetDock(hint, Dock.Top);
        root.Children.Add(hint);
        root.Children.Add(scroll);
        Content = root;
    }

    private static Canvas Draw(TopologyNode[] nodes, TopologyLink[] links)
    {
        var canvas = new Canvas { Width = Math.Max(720, Math.Min(4000, nodes.Length * 95)),
            Height = Math.Max(360, Math.Min(3000, nodes.Length * 45)) };
        var coordinates = new Dictionary<int, Point>();
        var layers = nodes.GroupBy(node => node.Kv).OrderByDescending(group => group.Key).ToArray();
        if (layers.Length == 1 && nodes.Length > 1)
        {
            var centre = new Point(canvas.Width / 2, canvas.Height / 2);
            for (var i = 0; i < nodes.Length; i++)
            {
                var theta = i * 2 * Math.PI / nodes.Length;
                coordinates[nodes[i].Id] = new Point(centre.X + (centre.X - 65) * Math.Cos(theta),
                    centre.Y + (centre.Y - 52) * Math.Sin(theta));
            }
        }
        else for (var layer = 0; layer < layers.Length; layer++)
        {
            var row = layers[layer].ToArray();
            for (var i = 0; i < row.Length; i++)
                coordinates[row[i].Id] = new Point((canvas.Width - 85) * (i + 1) / (row.Length + 1),
                    canvas.Height * (layer + 1) / (layers.Length + 1));
        }
        foreach (var link in links)
        {
            if (!coordinates.TryGetValue(link.From, out var origin) || !coordinates.TryGetValue(link.To, out var end)) continue;
            canvas.Children.Add(new Line { X1 = origin.X, Y1 = origin.Y, X2 = end.X, Y2 = end.Y,
                Stroke = link.Type == "trafo" ? Brushes.SteelBlue : Brushes.Gray, StrokeThickness = 1.6,
                StrokeDashArray = link.Closed ? null : new DoubleCollection([4, 3]), ToolTip = link.Type });
        }
        foreach (var node in nodes)
        {
            var point = coordinates[node.Id];
            var dot = new Ellipse { Width = 14, Height = 14, Fill = node.Active ? Brushes.DarkSlateBlue : Brushes.Gray };
            Canvas.SetLeft(dot, point.X - 7);
            Canvas.SetTop(dot, point.Y - 7);
            canvas.Children.Add(dot);
            var label = new TextBlock { Text = $"Bus {node.Id} · {node.Kv:G4} kV", Background = Brushes.WhiteSmoke };
            Canvas.SetLeft(label, point.X + 9);
            Canvas.SetTop(label, point.Y - 8);
            canvas.Children.Add(label);
        }
        return canvas;
    }
}
