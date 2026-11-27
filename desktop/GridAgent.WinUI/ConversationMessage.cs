using System.ComponentModel;
using System.Text;

namespace GridAgent.Windows;

internal sealed record ScientificChartArtifact(string RunId, string Path, string Sha256, string Title,
    string XLabel, string YLabel, int SeriesCount, int Points, string ViewKind = "chart", string Summary = "");

internal sealed record ResearchSnapshot(string Id, string Stage, string Summary, int RunsUsed, int MaxRuns);

internal sealed class ConversationMessage(string role, string body) : INotifyPropertyChanged
{
    public string Role { get; } = role;
    public string Body { get; } = body;
    private readonly StringBuilder _stream = new();
    public string StreamText => _stream.ToString();
    public void AddDelta(string delta)
    {
        _stream.Append(delta);
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(StreamText)));
    }
    private readonly List<string> _activity = new();
    public IReadOnlyList<string> Activity => _activity;
    public int ActivityCount { get; private set; }
    public string Latest { get; private set; } = "";
    public Action<string>? OpenRun { get; init; }
    public Action<string>? RequestPreview { get; init; }
    public RunArtifact? Artifact { get; init; }
    public ScientificChartArtifact? ScientificChart { get; init; }
    public Action<ScientificChartArtifact>? OpenScientificChart { get; init; }
    public RunPreview? Preview { get; private set; }
    public void SetPreview(RunPreview preview)
    {
        if (Artifact?.Id != preview.Id) return;
        Preview = preview;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Preview)));
    }
    public Action<string>? OpenTask { get; init; }
    public ResearchSnapshot? Research { get; private set; }
    public void SetResearch(ResearchSnapshot snapshot)
    {
        if (snapshot == Research) return;
        Research = snapshot;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Research)));
    }
    public event PropertyChangedEventHandler? PropertyChanged;
    public void AddActivity(string summary)
    {
        ActivityCount++;
        Latest = summary.Split('\n')[0];
        if (Latest.Length > 160) Latest = Latest[..160] + "…";
        // Bound the UI activity log; the durable task history remains in the workspace.
        if (_activity.Count == 100) _activity.RemoveAt(0);
        _activity.Add(summary.Length > 1200 ? summary[..1200] + "…" : summary);
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Activity)));
    }
}
