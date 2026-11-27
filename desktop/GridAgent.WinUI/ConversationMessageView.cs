using System.ComponentModel;
using System.Text;
using Markdig;
using Markdig.Syntax;
using Block = Markdig.Syntax.Block;
using Markdig.Syntax.Inlines;
using Markdig.Extensions.Tables;
using Markdig.Extensions.Mathematics;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Text;

namespace GridAgent.Windows;

public sealed class ConversationMessageView : UserControl
{
    private ConversationMessage? _message;
    private Expander? _activity;
    private StackPanel? _details;
    private TextBlock? _streamText;
    private TextBlock? _researchStage;
    private TextBlock? _researchSummary;
    private ProgressBar? _researchProgress;
    private ContentControl? _artifactHost;
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
        Detach(); _activity = null; _details = null; _streamText = null; _researchStage = null; _researchSummary = null; _researchProgress = null; _artifactHost = null; Content = null;
        if (message == null) return;
        _message = message;
        var layout = new Grid { MaxWidth = 820, HorizontalAlignment = HorizontalAlignment.Stretch, Padding = new Thickness(8, 8, 8, 14) };
        if (message.Role == "Activity")
        {
            _details = new StackPanel { Spacing = 8 };
            _activity = new Expander { HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch, Content = _details };
            _activity.Expanding += (_, _) => UpdateActivity();
            _activity.Collapsed += (_, _) => _details?.Children.Clear();
            layout.Children.Add(_activity);
            message.PropertyChanged += MessageChanged;
            UpdateActivity();
        }
        else if (message.ScientificChart is ScientificChartArtifact chart)
        {
            var panel = new StackPanel { Spacing = 8 };
            panel.Children.Add(new TextBlock { Text = chart.Title, FontSize = 18,
                FontWeight = FontWeights.SemiBold, TextWrapping = TextWrapping.Wrap });
            panel.Children.Add(Plain(chart.ViewKind == "chart" ? $"{chart.XLabel} · {chart.YLabel} · {chart.SeriesCount} series · {chart.Points} samples" : $"{chart.ViewKind} · {chart.Summary}", 13));
            panel.Children.Add(Metadata("Unverified script output · Run " + chart.RunId[..8]));
            var open = new Button { Content = "Open scientific view", HorizontalAlignment = HorizontalAlignment.Left };
            open.Click += (_, _) => message.OpenScientificChart?.Invoke(chart);
            panel.Children.Add(open);
            layout.Children.Add(new Border { Style = (Style)Application.Current.Resources["EngineeringCardStyle"],
                Child = panel });
        }
        else if (message.Artifact != null)
        {
            _artifactHost = new ContentControl { HorizontalContentAlignment = HorizontalAlignment.Stretch };
            layout.Children.Add(_artifactHost);
            message.PropertyChanged += MessageChanged;
            RefreshArtifact();
        }
        else if (message.Role == "Streaming")
        {
            // During streaming use inexpensive text; render Markdown once on finalization.
            _streamText = Plain(message.StreamText);
            layout.Children.Add(_streamText);
            message.PropertyChanged += MessageChanged;
        }
        else if (message.Role == "Research")
        {
            var taskPanel = new StackPanel { Spacing = 10 };
            taskPanel.Children.Add(new TextBlock { Text = "Verified research task", FontWeight = FontWeights.SemiBold, FontSize = 18 });
            _researchStage = Plain("", 14);
            AutomationProperties.SetLiveSetting(_researchStage, AutomationLiveSetting.Polite);
            _researchProgress = new ProgressBar { Minimum = 0, Maximum = 1 };
            AutomationProperties.SetName(_researchProgress, "Simulation budget usage");
            _researchSummary = Plain("", 14);
            taskPanel.Children.Add(_researchStage);
            taskPanel.Children.Add(_researchProgress);
            taskPanel.Children.Add(new Expander { Header = "Task details", Content = _researchSummary, HorizontalAlignment = HorizontalAlignment.Stretch });
            var open = new Button { Content = "Open research task", HorizontalAlignment = HorizontalAlignment.Left };
            open.Click += (_, _) => { if (message.Research is ResearchSnapshot task) message.OpenTask?.Invoke(task.Id); };
            taskPanel.Children.Add(open);
            layout.Children.Add(new Border { Style = (Style)Application.Current.Resources["EngineeringCardStyle"], Padding = new Thickness(16),
                BorderThickness = new Thickness(1), Child = taskPanel });
            message.PropertyChanged += MessageChanged;
            UpdateResearch();
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

    private void MessageChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(ConversationMessage.Preview)) RefreshArtifact();
        else if (e.PropertyName == nameof(ConversationMessage.StreamText) && _streamText != null && _message != null)
            _streamText.Text = _message.StreamText;
        else if (e.PropertyName == nameof(ConversationMessage.Research)) UpdateResearch();
        else UpdateActivity();
    }
    private void RefreshArtifact()
    {
        if (_artifactHost != null && _message?.Artifact != null) _artifactHost.Content = RunArtifactView.Create(_message);
    }
    private void UpdateResearch()
    {
        if (_message?.Research is not ResearchSnapshot task || _researchStage == null || _researchProgress == null || _researchSummary == null) return;
        _researchStage.Text = $"{task.Stage.Replace('_', ' ')} · {task.RunsUsed}/{task.MaxRuns} simulations used";
        _researchProgress.Maximum = Math.Max(1, task.MaxRuns);
        _researchProgress.Value = Math.Clamp(task.RunsUsed, 0, Math.Max(1, task.MaxRuns));
        _researchSummary.Text = task.Summary;
    }
    private void UpdateActivity()
    {
        if (_activity == null || _message == null || _details == null) return;
        _activity.Header = $"{_message.ActivityCount} engineering actions · {_message.Latest}";
        if (!_activity.IsExpanded) return;
        _details.Children.Clear();
        if (_message.ActivityCount > _message.Activity.Count)
            _details.Children.Add(Plain("Showing the most recent 100 summaries."));
        foreach (var line in _message.Activity) _details.Children.Add(Plain(line, 13));
    }
    internal static TextBlock Metadata(string text)
    {
        var block = Plain(text, 13);
        block.Style = (Style)Application.Current.Resources["ConversationMetadataStyle"];
        return block;
    }
    internal static TextBlock Plain(string text, double size = 15) => new()
    { Text = text, FontSize = size, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true, LineHeight = size * 1.45 };
}

internal static class NativeMarkdown
{
    private static readonly MarkdownPipeline Pipeline = new MarkdownPipelineBuilder().UsePipeTables().UseMathematics().DisableHtml().Build();
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
            case MathBlock math:
                panel.Children.Add(NativeMath.Create(math.Lines.ToString(), true)); break;
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
                            foreach (var t in cell.Children.OfType<RichTextBlock>()) t.FontWeight = FontWeights.SemiBold;
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
            case ThematicBreakBlock: panel.Children.Add(new Border { Height = 1, Padding = new Thickness(0), Style = (Style)Application.Current.Resources["EngineeringCardStyle"], BorderThickness = new Thickness(0, 0, 0, 1) }); break;
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
    private static RichTextBlock InlineText(ContainerInline? inline)
    {
        var text = new RichTextBlock { FontSize = 15, IsTextSelectionEnabled = true, TextWrapping = TextWrapping.Wrap, LineHeight = 22 };
        var paragraph = new Microsoft.UI.Xaml.Documents.Paragraph();
        if (inline != null) AddInline(paragraph.Inlines, inline, false, false);
        text.Blocks.Add(paragraph);
        return text;
    }
    private static void AddInline(InlineCollection target, ContainerInline container, bool bold, bool italic)
    {
        foreach (var item in container)
        {
            switch (item)
            {
                case LiteralInline literal: AddRun(literal.Content.ToString()); break;
                case MathInline math:
                    target.Add(new InlineUIContainer { Child = NativeMath.Create(math.Content.ToString(), false) }); break;
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
