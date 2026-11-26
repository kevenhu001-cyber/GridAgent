using CSharpMath.SkiaSharp;
using SkiaSharp;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Automation;
using Windows.Storage.Streams;

namespace GridAgent.Windows;

// Render a bounded subset of TeX locally. No browser, network, shell or file access.
internal static class NativeMath
{
    private const int CacheEntries = 96;
    private const int CacheBytes = 8 * 1024 * 1024;
    private static readonly object Gate = new();
    private static readonly Dictionary<(string Latex, bool Dark, bool Display), byte[]> Cache = new();
    private static readonly Queue<(string Latex, bool Dark, bool Display)> Order = new();
    private static int _bytes;

    public static FrameworkElement Create(string latex, bool display)
    {
        var source = latex.Trim();
        var fallback = ConversationMessageView.Plain(source, 14);
        fallback.FontFamily = new FontFamily("Cambria Math");
        var image = new Image { Stretch = Stretch.Uniform, MaxWidth = display ? 760 : 420, MaxHeight = display ? 260 : 90, Visibility = Visibility.Collapsed };
        var panel = new Grid { VerticalAlignment = VerticalAlignment.Center };
        panel.Children.Add(fallback); panel.Children.Add(image);
        AutomationProperties.SetName(panel, "Math formula: " + source);
        ToolTipService.SetToolTip(panel, source);
        if (display) panel.Margin = new Thickness(0, 6, 0, 6);
        int generation = 0;
        async Task Render()
        {
            int request = ++generation;
            fallback.Visibility = Visibility.Visible; image.Visibility = Visibility.Collapsed;
            try
            {
                bool dark = panel.ActualTheme == ElementTheme.Dark;
                var bytes = await Task.Run(() => Raster(source, dark, display));
                if (bytes == null || request != generation || !panel.IsLoaded) return;
                using var stream = new InMemoryRandomAccessStream();
                using (var writer = new DataWriter(stream))
                {
                    writer.WriteBytes(bytes);
                    await writer.StoreAsync();
                    writer.DetachStream();
                }
                stream.Seek(0);
                var bitmap = new BitmapImage();
                await bitmap.SetSourceAsync(stream);
                if (request != generation || !panel.IsLoaded || bitmap.PixelWidth < 1 || bitmap.PixelHeight < 1) return;
                image.Source = bitmap;
                // Supersampled at 2x for legibility on DPI-scaled displays.
                image.Width = Math.Min(display ? 760 : 420, bitmap.PixelWidth / 2.0);
                image.Height = Math.Min(display ? 260 : 90, bitmap.PixelHeight / 2.0);
                image.Visibility = Visibility.Visible; fallback.Visibility = Visibility.Collapsed;
            }
            catch (Exception) { /* Keep selectable LaTeX source when unsupported or unavailable. */ }
        }
        panel.Loaded += async (_, _) => await Render();
        panel.ActualThemeChanged += async (_, _) => await Render();
        panel.Unloaded += (_, _) => { generation++; image.Source = null; };
        return panel;
    }

    internal static byte[]? Raster(string source, bool dark, bool display)
    {
        // Bound parsing complexity, formula size and cache memory for untrusted model text.
        if (source.Length is < 1 or > 512) return null;
        int depth = 0;
        foreach (char c in source)
        {
            if (c == '{' && ++depth > 18) return null;
            if (c == '}' && --depth < 0) return null;
        }
        if (depth != 0) return null;
        var key = (source, dark, display);
        lock (Gate)
        {
            if (Cache.TryGetValue(key, out var cached)) return cached;
            var painter = new MathPainter { LaTeX = source, FontSize = display ? 36 : 30,
                TextColor = dark ? SKColors.White : SKColors.Black };
            if (!string.IsNullOrEmpty(painter.ErrorMessage)) return null;
            using var png = painter.DrawAsStream();
            if (png == null) return null;
            using var buffer = new System.IO.MemoryStream();
            png.CopyTo(buffer);
            if (buffer.Length is < 1 or > 512 * 1024) return null;
            var bytes = buffer.ToArray();
            while (Order.Count >= CacheEntries || _bytes + bytes.Length > CacheBytes)
            {
                var old = Order.Dequeue(); _bytes -= Cache[old].Length; Cache.Remove(old);
            }
            Cache[key] = bytes; Order.Enqueue(key); _bytes += bytes.Length;
            return bytes;
        }
    }
}
