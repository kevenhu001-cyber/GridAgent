using System.Globalization;
using System.Windows;
using System.Windows.Controls;

namespace GridAgent.Windows;

internal sealed class ClearingTimeWindow : Window
{
    private readonly TextBox _input = new() { Text = "1.16", Margin = new Thickness(0, 8, 0, 12) };
    public string Value { get; private set; } = "";
    public ClearingTimeWindow()
    {
        Title = "Fault clearing time";
        Width = 380; Height = 190; ResizeMode = ResizeMode.NoResize;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var panel = new StackPanel { Margin = new Thickness(20) };
        panel.Children.Add(new TextBlock { Text = "Absolute clearing time in seconds (fault starts at 1 s)" });
        panel.Children.Add(_input);
        var ok = new Button { Content = "Compute KPI", IsDefault = true };
        ok.Click += (_, _) =>
        {
            if (!double.TryParse(_input.Text, NumberStyles.Float, CultureInfo.InvariantCulture, out double t)
                || !double.IsFinite(t) || t <= 1)
            { MessageBox.Show(this, "Enter a finite time greater than 1 second."); return; }
            Value = t.ToString(CultureInfo.InvariantCulture);
            DialogResult = true;
        };
        panel.Children.Add(ok); Content = panel;
    }
}
