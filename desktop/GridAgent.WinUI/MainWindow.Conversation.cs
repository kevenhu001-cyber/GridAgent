using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace GridAgent.Windows;

public partial class MainWindow
{
    private ScrollViewer? _conversationViewport;
    private bool _followTail = true;
    private void ClearMessages() { _conversation.Clear(); _followTail = true; JumpToLatest.Visibility = Visibility.Collapsed; EmptyConversation.Visibility = Visibility.Visible; }
    private void Notify(string message, InfoBarSeverity severity = InfoBarSeverity.Informational)
    {
        Notice.Message = message; Notice.Severity = severity; Notice.IsOpen = true;
    }
    private void UpdateModelCaption() => ConversationModel.Text = string.IsNullOrWhiteSpace(ModelName.Text) ? "Engineering assistant" : ModelName.Text.Trim();
    private void OpenConversationHistory(object sender, RoutedEventArgs e) =>
        Navigation.SelectedItem = Navigation.MenuItems.OfType<NavigationViewItem>().First(i => (string)i.Tag == "studies");
    private void UseSuggestion(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Content is string text) { Prompt.Text = text; Prompt.Focus(FocusState.Programmatic); }
    }
    private bool _scrollQueued;
    private void ConversationLoaded(object sender, RoutedEventArgs e)
    {
        static ScrollViewer? FindViewport(DependencyObject node)
        {
            for (int i = 0; i < VisualTreeHelper.GetChildrenCount(node); i++)
            {
                var child = VisualTreeHelper.GetChild(node, i);
                if (child is ScrollViewer scroll) return scroll;
                if (FindViewport(child) is ScrollViewer found) return found;
            }
            return null;
        }
        if (_conversationViewport != null) _conversationViewport.ViewChanged -= ConversationViewChanged;
        _conversationViewport = FindViewport(Messages);
        if (_conversationViewport != null) _conversationViewport.ViewChanged += ConversationViewChanged;
    }
    private void ConversationViewChanged(object? sender, ScrollViewerViewChangedEventArgs args)
    {
        if (_conversationViewport == null || _scrollQueued) return;
        _followTail = _conversationViewport.ScrollableHeight - _conversationViewport.VerticalOffset <= 80;
        JumpToLatest.Visibility = _followTail ? Visibility.Collapsed : Visibility.Visible;
    }
    private void JumpToLatestClick(object sender, RoutedEventArgs e)
    {
        _followTail = true;
        JumpToLatest.Visibility = Visibility.Collapsed;
        QueueConversationScroll();
    }
    private void QueueConversationScroll()
    {
        if (_scrollQueued || _messages.Count == 0 || !_followTail) return;
        // Coalesce bursts of history and tool updates into one dispatcher callback.
        _scrollQueued = true;
        DispatcherQueue.TryEnqueue(() =>
        {
            _scrollQueued = false;
            if (_messages.Count > 0 && _followTail) Messages.ScrollIntoView(_messages[^1]);
        });
    }
    private void UpdateConversationViewport()
    {
        EmptyConversation.Visibility = _messages.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        QueueConversationScroll();
    }
    private void Append(string text, string role = "Result")
    {
        if (role == "You") { _followTail = true; JumpToLatest.Visibility = Visibility.Collapsed; }
        _conversation.Append(role, text);
        UpdateConversationViewport();
    }
    private void AppendDelta(string delta) { _conversation.Delta(delta); UpdateConversationViewport(); }
    private void FinishStream(string finalText) { _conversation.Complete(finalText); UpdateConversationViewport(); }
    private void InterruptStream() { _conversation.Interrupt(); UpdateConversationViewport(); }
    private async void LoadArtifactPreview(string id)
    {
        if (_busy || WorkspaceChanged() || !_conversation.HasArtifact(id))
        { Notify("Wait for the current operation before loading a chart preview.", InfoBarSeverity.Warning); return; }
        await Execute(new { action = "artifact-preview", run = id });
    }
    private void AddArtifact(RunArtifact artifact)
    {
        _conversation.Artifact(artifact, OpenArtifactRun, LoadArtifactPreview);
        UpdateConversationViewport();
    }
    private void AddTool(string label) { _conversation.Activity(label); UpdateConversationViewport(); }
}
