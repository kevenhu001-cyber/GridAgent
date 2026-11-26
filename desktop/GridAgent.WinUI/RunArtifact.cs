using System.Text.Json;
using System.Text.RegularExpressions;

namespace GridAgent.Windows;

// Presentation DTOs are independent of WinUI; reject unsupported versions and unsafe shapes.
internal sealed record ArtifactMetric(string Name, double Value);
internal sealed record ArtifactQuality(int Passed, int Total, string Protocol);
internal sealed record RunArtifact(string Id, string Backend, string Operation, string Status, string Case,
    ArtifactQuality? Quality, ArtifactMetric[] Metrics, string[] Views)
{
    public bool HasPreview => Views.Contains("waveform") || Views.Contains("analysis");
    private const string Schema = "gridagent.artifact.v1";
    internal static bool Valid(JsonElement data, string kind) =>
        data.ValueKind == JsonValueKind.Object && data.TryGetProperty("schema", out var schema) &&
        schema.GetString() == Schema && data.TryGetProperty("kind", out var type) && type.GetString() == kind &&
        data.TryGetProperty("id", out var id) && id.ValueKind == JsonValueKind.String &&
        Regex.IsMatch(id.GetString() ?? "", "^[a-f0-9]{32}$");
    internal static string Label(JsonElement data, string key) =>
        data.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String
            ? (value.GetString() ?? "")[..Math.Min(120, (value.GetString() ?? "").Length)] : "unknown";

    public static RunArtifact? Parse(JsonElement data)
    {
        if (!Valid(data, "run")) return null;
        ArtifactQuality? quality = null;
        if (data.TryGetProperty("quality", out var q) && q.ValueKind == JsonValueKind.Object &&
            q.TryGetProperty("passed", out var passed) && passed.TryGetInt32(out int p) &&
            q.TryGetProperty("total", out var total) && total.TryGetInt32(out int t) && 0 <= p && p <= t && t <= 10000)
            quality = new ArtifactQuality(p, t, Label(q, "protocol"));
        var metrics = new List<ArtifactMetric>();
        if (data.TryGetProperty("metrics", out var rows) && rows.ValueKind == JsonValueKind.Array)
            foreach (var row in rows.EnumerateArray().Take(12))
                if (row.ValueKind == JsonValueKind.Object && row.TryGetProperty("value", out var value) &&
                    value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var number) && double.IsFinite(number))
                    metrics.Add(new ArtifactMetric(Label(row, "name"), number));
        var views = data.TryGetProperty("views", out var v) && v.ValueKind == JsonValueKind.Array
            ? v.EnumerateArray().Take(8).Where(x => x.ValueKind == JsonValueKind.String)
                .Select(x => x.GetString()!).Where(x => x is "waveform" or "analysis" or "topology").Distinct().ToArray()
            : Array.Empty<string>();
        return new RunArtifact(data.GetProperty("id").GetString()!, Label(data, "backend"), Label(data, "operation"),
            Label(data, "status"), Label(data, "case"), quality, metrics.ToArray(), views);
    }
}
internal sealed record RunPreview(string Id, string Title, string XLabel, string YLabel, bool Scatter,
    int SourcePoints, double[] X, double[] Y)
{
    public static RunPreview? Parse(JsonElement data)
    {
        if (!RunArtifact.Valid(data, "chart-preview") ||
            !data.TryGetProperty("x", out var x) || x.ValueKind != JsonValueKind.Array ||
            !data.TryGetProperty("y", out var y) || y.ValueKind != JsonValueKind.Array ||
            x.GetArrayLength() != y.GetArrayLength() || x.GetArrayLength() is < 1 or > 240 ||
            !data.TryGetProperty("source_points", out var count) || !count.TryGetInt32(out var n) || n < x.GetArrayLength() ||
            !data.TryGetProperty("scatter", out var scatter) || scatter.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
            return null;
        var xs = x.EnumerateArray().Select(v => v.ValueKind == JsonValueKind.Number && v.TryGetDouble(out var d) ? d : double.NaN).ToArray();
        var ys = y.EnumerateArray().Select(v => v.ValueKind == JsonValueKind.Number && v.TryGetDouble(out var d) ? d : double.NaN).ToArray();
        if (xs.Any(v => !double.IsFinite(v)) || ys.Any(v => !double.IsFinite(v))) return null;
        return new RunPreview(data.GetProperty("id").GetString()!, RunArtifact.Label(data, "title"), RunArtifact.Label(data, "x_label"),
            RunArtifact.Label(data, "y_label"), scatter.GetBoolean(), n, xs, ys);
    }
}
