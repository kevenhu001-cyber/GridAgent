using System.Collections.ObjectModel;

namespace GridAgent.Windows;

// UI-agnostic conversation projection. All mutation occurs on the caller's UI dispatcher.
// Durable authoritative history belongs to the Python workspace, not this view model.
internal sealed class ConversationState
{
    private readonly ObservableCollection<ConversationMessage> _items = new();
    private readonly Dictionary<string, ConversationMessage> _artifacts = new(StringComparer.Ordinal);
    private ConversationMessage? _activity, _stream, _research;
    public ReadOnlyObservableCollection<ConversationMessage> Messages { get; }
    public ConversationState() => Messages = new(_items);
    public void Clear()
    {
        _items.Clear(); _artifacts.Clear(); _activity = _stream = _research = null;
    }
    public void BeginOperation() { _research = null; _activity = null; }
    public void Append(string role, string text)
    {
        if (string.IsNullOrWhiteSpace(text)) return;
        _activity = null;
        _items.Add(new ConversationMessage(role, text));
    }
    public void Delta(string text)
    {
        if (string.IsNullOrEmpty(text)) return;
        _activity = null;
        if (_stream == null)
        {
            _stream = new ConversationMessage("Streaming", "");
            _items.Add(_stream);
        }
        _stream.AddDelta(text);
    }
    public void Complete(string finalText)
    {
        if (_stream == null) { Append("Assistant", finalText); return; }
        int index = _items.IndexOf(_stream);
        if (index >= 0)
        {
            if (string.IsNullOrWhiteSpace(finalText)) _items.RemoveAt(index);
            else _items[index] = new ConversationMessage("Assistant", finalText);
        }
        _stream = null;
    }
    public void Interrupt()
    {
        if (_stream == null) return;
        int index = _items.IndexOf(_stream);
        if (index >= 0) _items[index] = new ConversationMessage("Interrupted response", _stream.StreamText);
        _stream = null;
    }
    public void Activity(string summary)
    {
        if (_activity == null)
        {
            _activity = new ConversationMessage("Activity", "");
            _items.Add(_activity);
        }
        _activity.AddActivity(summary);
    }
    public void Research(ResearchSnapshot snapshot, Action<string> openTask)
    {
        _activity = null;
        if (_research?.Research?.Id != snapshot.Id)
        {
            _research = new ConversationMessage("Research", "") { OpenTask = openTask };
            _research.SetResearch(snapshot);
            _items.Add(_research);
        }
        else _research.SetResearch(snapshot);
    }
    public bool HasArtifact(string id) => _artifacts.ContainsKey(id);
    public void Artifact(RunArtifact artifact, Action<string> openRun, Action<string> preview)
    {
        if (_artifacts.ContainsKey(artifact.Id)) return;
        var item = new ConversationMessage("Artifact", "") { Artifact = artifact, OpenRun = openRun, RequestPreview = preview };
        _artifacts.Add(artifact.Id, item);
        _items.Add(item);
        _activity = null;
    }
    public void Preview(RunPreview preview)
    {
        if (_artifacts.TryGetValue(preview.Id, out var item)) item.SetPreview(preview);
    }
}
