using System.ComponentModel;
using System.Text;
using Markdig;
using Markdig.Syntax;
using Block = Markdig.Syntax.Block;
using Markdig.Syntax.Inlines;
using Markdig.Extensions.Tables;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Text;

namespace GridAgent.Windows;

internal sealed class ConversationMessage(string role, string body) : INotifyPropertyChanged
{
    public string Role { get; } = role;
    public string Body { get; } = body;
    private readonly List<string> _activity = new();
    public IReadOnlyList<string> Activity => _activity;
    public int ActivityCount { get; private set; }
    public string Latest { get; private set; } = "";
    public string? LatestRun { get; private set; }
    public Action<string>? OpenRun { get; init; }
    public event PropertyChangedEventHandler? PropertyChanged;
    public void AddActivity(string summary)
    {
        ActivityCount++;
        var run = System.Text.RegularExpressions.Regex.Match(summary, @"\brun ([a-f0-9]{32})\b");
        if (run.Success) LatestRun = run.Groups[1].Value;
        Latest = summary.Split('\n')[0];
        if (Latest.Length > 160) Latest = Latest[..160] + "…";
        // Bound the UI activity log; the durable task history remains in the workspace.
        if (_activity.Count == 100) _activity.RemoveAt(0);
        _activity.Add(summary.Length > 1200 ? summary[..1200] + "…" : summary);
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Activity)));
    }
}

public sealed class ConversationMessageView : UserControl
{
    private ConversationMessage? _message;
    private Expander? _activity;
    private StackPanel? _details;
    private Button? _openRun;
    public ConversationMessageView()
    {
        HorizontalContentAlignment = HorizontalAlignment.Stretch;
        DataContextChanged += (_, _) => Bind(DataContext as ConversationMessage);
        Unloaded += (_, _) => Detach();
        Loaded += (_, _) => { if (_message == null) Bind(DataContext as ConversationMessage); };
    }
    private void Detach()
    {
        if (_message != null) _message.PropertyChanged -= MessageChanged;
        _message = null;
    }
    private void Bind(ConversationMessage? message)
    {
        if (ReferenceEquals(message, _message)) return;
        Detach(); _activity = null; _details = null; _openRun = null; Content = null;
        if (message == null) return;
        _message = message;
        var layout = new Grid { MaxWidth = 820, HorizontalAlignment = HorizontalAlignment.Stretch, Padding = new Thickness(8, 8, 8, 14) };
        if (message.Role == "Activity")
        {
            _details = new StackPanel { Spacing = 8 };
            _activity = new Expander { HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch, Content = _details };
            _activity.Expanding += (_, _) => UpdateActivity();
            _activity.Collapsed += (_, _) => _details?.Children.Clear();
            var activityLayout = new StackPanel { Spacing = 6 };
            activityLayout.Children.Add(_activity);
            _openRun = new Button { Content = "Open simulation result", Visibility = Visibility.Collapsed, HorizontalAlignment = HorizontalAlignment.Left };
            _openRun.Click += (_, _) => { if (message.LatestRun is string id) message.OpenRun?.Invoke(id); };
            activityLayout.Children.Add(_openRun);
            layout.Children.Add(activityLayout);
            message.PropertyChanged += MessageChanged;
            UpdateActivity();
        }
        else if (message.Role == "You")
        {
            var text = Plain(message.Body);
            var bubble = new Border { Style = (Style)Application.Current.Resources["UserMessageCardStyle"], CornerRadius = new CornerRadius(18), Padding = new Thickness(16, 10, 16, 10), Child = text };
            AutomationProperties.SetName(bubble, "Your message");
            layout.Children.Add(bubble);
        }
        else
        {
            var stack = new StackPanel { Spacing = 8 };
            if (message.Role != "Assistant") stack.Children.Add(new TextBlock { Text = message.Role, FontWeight = FontWeights.SemiBold, FontSize = 12 });
            try { stack.Children.Add(NativeMarkdown.Render(message.Body)); }
            catch (Exception) { stack.Children.Add(Plain(message.Body)); }
            var copy = new Button { Content = new SymbolIcon(Symbol.Copy), Style = (Style)Application.Current.Resources["SubtleButtonStyle"], HorizontalAlignment = HorizontalAlignment.Left };
            AutomationProperties.SetName(copy, "Copy response");
            ToolTipService.SetToolTip(copy, "Copy response");
            copy.Click += (_, _) => Copy(message.Body);
            stack.Children.Add(copy);
            layout.Children.Add(stack);
        }
        Content = layout;
    }
    internal static void Copy(string value)
    {
        var data = new global::Windows.ApplicationModel.DataTransfer.DataPackage();
        data.SetText(value);
        global::Windows.ApplicationModel.DataTransfer.Clipboard.SetContent(data);
    }
    private void MessageChanged(object? sender, PropertyChangedEventArgs e) => UpdateActivity();
    private void UpdateActivity()
    {
        if (_activity == null || _message == null || _details == null) return;
        _activity.Header = $"{_message.ActivityCount} engineering actions · {_message.Latest}";
        if (_openRun != null) _openRun.Visibility = _message.LatestRun != null && _message.OpenRun != null ? Visibility.Visible : Visibility.Collapsed;
        if (!_activity.IsExpanded) return;
        _details.Children.Clear();
        if (_message.ActivityCount > _message.Activity.Count)
            _details.Children.Add(Plain("Showing the most recent 100 summaries."));
        foreach (var line in _message.Activity) _details.Children.Add(Plain(line, 13));
    }
    internal static TextBlock Plain(string text, double size = 15) => new()
    { Text = text, FontSize = size, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true, LineHeight = size * 1.45 };
}

internal static class NativeMarkdown
{
    private static readonly MarkdownPipeline Pipeline = new MarkdownPipelineBuilder().UsePipeTables().DisableHtml().Build();
    public static FrameworkElement Render(string source)
    {
        if (source.Length > 100_000) return ConversationMessageView.Plain(source);
        var stack = new StackPanel { Spacing = 10 };
        foreach (var block in Markdown.Parse(source, Pipeline)) AddBlock(stack, block, source, 0);
        return stack;
    }
    private static void AddBlock(StackPanel panel, Block block, string source, int depth)
    {
        if (depth > 8) { panel.Children.Add(ConversationMessageView.Plain(Raw(block, source))); return; }
        switch (block)
        {
            case HeadingBlock heading:
                var title = InlineText(heading.Inline); title.FontSize = heading.Level <= 2 ? 22 : 18;
                title.FontWeight = FontWeights.SemiBold; panel.Children.Add(title); break;
            case ParagraphBlock paragraph:
                panel.Children.Add(InlineText(paragraph.Inline)); break;
            case CodeBlock code:
                var value = code.Lines.ToString();
                var text = ConversationMessageView.Plain(value, 13);
                text.FontFamily = new FontFamily("Consolas"); text.TextWrapping = TextWrapping.NoWrap;
                var codePanel = new StackPanel { Spacing = 6 };
                var copy = new Button { Content = "Copy code", HorizontalAlignment = HorizontalAlignment.Right };
                copy.Click += (_, _) => ConversationMessageView.Copy(value);
                codePanel.Children.Add(copy);
                codePanel.Children.Add(new ScrollViewer { Content = text, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollMode = ScrollMode.Enabled, VerticalScrollMode = ScrollMode.Disabled });
                panel.Children.Add(Card(codePanel)); break;
            case Markdig.Extensions.Tables.Table table:
                var grid = new Grid { ColumnSpacing = 16, RowSpacing = 8 };
                var rows = table.OfType<TableRow>().ToArray();
                int columns = rows.Select(row => row.Count).DefaultIfEmpty(0).Max();
                if (columns > 12 || rows.Length > 100) { panel.Children.Add(ConversationMessageView.Plain(Raw(block, source))); break; }
                for (int i = 0; i < columns; i++) grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                for (int i = 0; i < rows.Length; i++)
                {
                    grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
                    for (int j = 0; j < rows[i].Count; j++)
                    {
                        var cell = new StackPanel { MinWidth = 72, Spacing = 4 };
                        if (rows[i][j] is TableCell c)
                            foreach (var child in c) AddBlock(cell, child, source, depth + 1);
                        if (rows[i].IsHeader)
                            foreach (var t in cell.Children.OfType<TextBlock>()) t.FontWeight = FontWeights.SemiBold;
                        Grid.SetRow(cell, i); Grid.SetColumn(cell, j); grid.Children.Add(cell);
                    }
                }
                panel.Children.Add(Card(new ScrollViewer { Content = grid, HorizontalScrollMode = ScrollMode.Enabled, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollMode = ScrollMode.Disabled })); break;
            case ListBlock list:
                int index = 1;
                if (list.IsOrdered && int.TryParse(list.OrderedStart, out int start)) index = start;
                foreach (var item in list.OfType<ListItemBlock>())
                {
                    var row = new Grid { ColumnSpacing = 8 };
                    row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                    row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                    row.Children.Add(ConversationMessageView.Plain(list.IsOrdered ? $"{index++}." : "•"));
                    var contents = new StackPanel { Spacing = 6 }; Grid.SetColumn(contents, 1); row.Children.Add(contents);
                    foreach (var child in item) AddBlock(contents, child, source, depth + 1);
                    panel.Children.Add(row);
                }
                break;
            case QuoteBlock quote:
                var quoted = new StackPanel { Spacing = 6 };
                foreach (var child in quote) AddBlock(quoted, child, source, depth + 1);
                panel.Children.Add(Card(quoted)); break;
            case ThematicBreakBlock: panel.Children.Add(new Border { Height = 1, Style = (Style)Application.Current.Resources["EngineeringCardStyle"], BorderThickness = new Thickness(0, 0, 0, 1) }); break;
            default: panel.Children.Add(ConversationMessageView.Plain(Raw(block, source))); break;
        }
    }
    private static string Raw(Block block, string source)
    {
        var start = Math.Clamp(block.Span.Start, 0, source.Length);
        var end = Math.Clamp(block.Span.End + 1, start, source.Length);
        return source[start..end];
    }
    private static Border Card(UIElement child) => new() { Child = child, Padding = new Thickness(12), CornerRadius = new CornerRadius(8), BorderThickness = new Thickness(1), Style = (Style)Application.Current.Resources["EngineeringCardStyle"] };
    private static TextBlock InlineText(ContainerInline? inline)
    {
        var text = ConversationMessageView.Plain("");
        if (inline != null) AddInline(text.Inlines, inline, false, false);
        return text;
    }
    private static void AddInline(InlineCollection target, ContainerInline container, bool bold, bool italic)
    {
        foreach (var item in container)
        {
            switch (item)
            {
                case LiteralInline literal: AddRun(literal.Content.ToString()); break;
                case CodeInline code: AddRun(code.Content, true); break;
                case LineBreakInline: target.Add(new Microsoft.UI.Xaml.Documents.LineBreak()); break;
                case EmphasisInline emphasis: AddInline(target, emphasis, bold || emphasis.DelimiterCount >= 2, italic || emphasis.DelimiterCount == 1); break;
                case LinkInline link:
                    // Links remain plain selectable text; no untrusted navigation or remote image loading.
                    AddInline(target, link, bold, italic);
                    if (!string.IsNullOrEmpty(link.Url)) AddRun(" (" + link.Url + ")");
                    break;
                case ContainerInline child: AddInline(target, child, bold, italic); break;
                default: AddRun(item.ToString() ?? ""); break;
            }
        }
        void AddRun(string value, bool mono = false)
        {
            var run = new Microsoft.UI.Xaml.Documents.Run { Text = value, FontWeight = bold ? FontWeights.SemiBold : FontWeights.Normal, FontStyle = italic ? global::Windows.UI.Text.FontStyle.Italic : global::Windows.UI.Text.FontStyle.Normal };
            if (mono) run.FontFamily = new FontFamily("Consolas");
            target.Add(run);
        }
    }
}
