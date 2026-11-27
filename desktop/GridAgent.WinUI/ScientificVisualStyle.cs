using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Automation;
using Color = global::Windows.UI.Color;

namespace GridAgent.Windows;

// Shared viewer controls and data colors; native theme resources own shell chrome.
internal static class ScientificVisualStyle
{
    private static readonly Color[] Light = {
        Color.FromArgb(255, 37, 99, 235), Color.FromArgb(255, 194, 65, 12),
        Color.FromArgb(255, 4, 120, 87), Color.FromArgb(255, 126, 34, 206),
        Color.FromArgb(255, 161, 98, 7), Color.FromArgb(255, 14, 116, 144)
    };
    private static readonly Color[] Dark = {
        Color.FromArgb(255, 96, 165, 250), Color.FromArgb(255, 251, 146, 60),
        Color.FromArgb(255, 52, 211, 153), Color.FromArgb(255, 192, 132, 252),
        Color.FromArgb(255, 250, 204, 21), Color.FromArgb(255, 103, 232, 249)
    };
    public static Color Series(ElementTheme theme, int i) =>
        (theme == ElementTheme.Dark ? Dark : Light)[i % Light.Length];
    public static Color Ink(ElementTheme theme) => theme == ElementTheme.Dark ? Microsoft.UI.Colors.White : Microsoft.UI.Colors.Black;
    public static Color Gridline => Color.FromArgb(42, 128, 128, 128);
    public static TextBlock Title(string text) => new()
    {
        Text = text, FontSize = 20, FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
        TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true
    };
    public static Button Action(string label, string glyph)
    {
        var button = new Button
        {
            Style = (Style)Application.Current.Resources["ConversationIconButtonStyle"],
            Content = new FontIcon { Glyph = glyph, FontSize = 16 }
        };
        AutomationProperties.SetName(button, label);
        ToolTipService.SetToolTip(button, label);
        return button;
    }
}
