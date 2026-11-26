using System.Text.Json;
using System.Windows;
using System.Windows.Controls;

namespace GridAgent.Windows;

internal sealed class PluginCenterWindow : Window
{
    public string? SelectedId { get; private set; }
    public string? Command { get; private set; }

    public PluginCenterWindow(JsonElement catalog)
    {
        Title = "Simulation Plugins";
        Width = 560; Height = 480; MinWidth = 420; MinHeight = 350;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var stack = new StackPanel { Margin = new Thickness(20) };
        stack.Children.Add(new TextBlock { Text = "Built in: ANDES · pandapower · scientific computing", FontWeight = FontWeights.SemiBold });
        stack.Children.Add(new TextBlock { Text = "Optional solvers are downloaded into your local user profile and loaded in a separate process. Installation requires internet access.", TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 8, 0, 18) });
        foreach (var item in catalog.EnumerateArray())
        {
            var id = item.GetProperty("id").GetString()!;
            var title = item.GetProperty("title").GetString()!;
            var installed = item.GetProperty("installed").GetBoolean();
            var managed = item.GetProperty("managed").GetBoolean();
            var requirements = string.Join(", ", item.GetProperty("requirements").EnumerateArray().Select(x => x.GetString()));
            var tools = string.Join(", ", item.GetProperty("tools").EnumerateArray().Select(x => x.GetString()));
            var panel = new DockPanel { Margin = new Thickness(0, 0, 0, 16) };
            var button = new Button { Content = managed ? "Uninstall" : installed ? "Available" : "Install",
                                      IsEnabled = managed || !installed, MinWidth = 90, Margin = new Thickness(10, 0, 0, 0) };
            DockPanel.SetDock(button, Dock.Right); panel.Children.Add(button);
            button.Click += (_, _) =>
            {
                var question = managed ? "Remove the managed " + title + " packages? Existing results are retained."
                    : "Download and install " + title + " from PyPI? Packages execute locally under your account. Requirements: " + requirements;
                if (MessageBox.Show(this, question, "Confirm plugin change", MessageBoxButton.OKCancel) != MessageBoxResult.OK) return;
                SelectedId = id; Command = managed ? "plugin-remove" : "plugin-install"; DialogResult = true;
            };
            var details = new StackPanel();
            details.Children.Add(new TextBlock { Text = title, FontWeight = FontWeights.SemiBold });
            details.Children.Add(new TextBlock { Text = (installed ? "Available" : "Not installed") + " · " + tools, TextWrapping = TextWrapping.Wrap });
            details.Children.Add(new TextBlock { Text = requirements, TextWrapping = TextWrapping.Wrap, FontSize = 11, Margin = new Thickness(0, 3, 0, 0) });
            panel.Children.Add(details); stack.Children.Add(panel);
        }
        Content = new ScrollViewer { Content = stack, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
    }
}
