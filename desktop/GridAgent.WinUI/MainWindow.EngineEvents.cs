using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace GridAgent.Windows;

public partial class MainWindow
{
    private void Handle(JsonElement evt)
    {
        var kind = evt.GetProperty("kind").GetString();
        var data = evt.GetProperty("data");
        switch (kind)
        {
            case "plugins": _pluginCatalog = data.Clone(); RenderPlugins(); break;
            case "model_settings":
                ModelName.Text = data.GetProperty("model").GetString() ?? "";
                BaseUrl.Text = data.GetProperty("base_url").GetString() ?? "";
                break;
            case "session": _session = data.GetString(); break;
            case "sessions":
                SetSessions(data.EnumerateArray().Select(x =>
                    new Entry(x.GetProperty("id").GetString()!,
                        x.GetProperty("title").GetString() + " · " + x.GetProperty("tasks").GetInt32())).ToList());
                break;
            case "studies":
                StudyList.ItemsSource = data.EnumerateArray().Select(x =>
                {
                    var id = x.GetProperty("id").GetString()!;
                    return new Entry(id, id[..Math.Min(12, id.Length)] + " · " + x.GetProperty("status").GetString());
                }).ToList();
                break;
            case "runs":
                RunList.ItemsSource = data.EnumerateArray().Select(x =>
                {
                    var id = x.GetProperty("id").GetString()!;
                    return new Entry(id, $"{x.GetProperty("operation")} · {x.GetProperty("case")} · {x.GetProperty("status")} · {id[..Math.Min(8, id.Length)]}");
                }).ToList();
                break;
            case "research_tasks":
                var selected = (ResearchList.SelectedItem as Entry)?.Id ?? _activeResearch;
                var tasks = data.EnumerateArray().Select(x => new Entry(x.GetProperty("id").GetString()!,
                    x.GetProperty("stage").GetString() + " · " + x.GetProperty("prompt").GetString())).ToList();
                ResearchList.ItemsSource = tasks;
                ResearchList.SelectedItem = tasks.FirstOrDefault(x => x.Id == selected);
                break;
            case "research_task":
                var researchId = data.GetProperty("id").GetString();
                var stage = data.GetProperty("stage").GetString();
                UpdateResearchCard(new ResearchSnapshot(researchId ?? "", stage ?? "unknown", data.GetProperty("summary").GetString() ?? "",
                    data.GetProperty("runs_used").GetInt32(), data.GetProperty("max_runs").GetInt32()));
                _activeResearch = researchId;
                CancelButton.Visibility = _busy && stage is not ("passed" or "failed" or "cancelled" or "awaiting_input" or "awaiting_approval") ? Visibility.Visible : Visibility.Collapsed;
                StatusText.Text = $"Research · {stage} · {data.GetProperty("runs_used")}/{data.GetProperty("max_runs")} simulations";
                break;
            case "topology": _topology = data.Clone(); break;
            case "model_revisions":
                _workspaceIndexLoaded = true;
                ModelRevisions.ItemsSource = data.EnumerateArray().Select(x =>
                {
                    var diff = x.GetProperty("diff");
                    return new Entry(x.GetProperty("id").GetString()!, x.GetProperty("name").GetString()!,
                        $"{diff.GetProperty("element")} {diff.GetProperty("index")} · {diff.GetProperty("field")} · " +
                        $"{diff.GetProperty("before")} → {diff.GetProperty("value")}\nParent run {x.GetProperty("parent_run")}\n" +
                        $"SHA-256 {x.GetProperty("sha256")}");
                }).ToList();
                break;
            case "scientific_view":
                var scientificView = new ScientificChartArtifact(data.GetProperty("run_id").GetString()!,
                    data.GetProperty("path").GetString()!, data.GetProperty("sha256").GetString()!,
                    data.GetProperty("title").GetString()!, "", "", 0, 0,
                    data.GetProperty("view_kind").GetString()!, data.GetProperty("summary").GetString()!);
                _conversation.ScientificChart(scientificView, OpenScientificChart);
                UpdateConversationViewport();
                break;
            case "scientific_view_data":
                var view = new ScientificDataView(data.Clone());
                OpenEngineeringWindow("Scientific results", view, view.Release);
                break;
            case "scientific_chart":
                var scientificChart = new ScientificChartArtifact(data.GetProperty("run_id").GetString()!,
                    data.GetProperty("path").GetString()!, data.GetProperty("sha256").GetString()!,
                    data.GetProperty("title").GetString()!, data.GetProperty("x_label").GetString()!,
                    data.GetProperty("y_label").GetString()!, data.GetProperty("series_count").GetInt32(),
                    data.GetProperty("points").GetInt32());
                _conversation.ScientificChart(scientificChart, OpenScientificChart);
                UpdateConversationViewport();
                break;
            case "analysis_charts":
                var charts = data.EnumerateArray().Select(chart => new ChartData(chart.GetProperty("title").GetString()!,
                    chart.GetProperty("x_label").GetString()!, chart.GetProperty("y_label").GetString()!,
                    chart.GetProperty("scatter").GetBoolean(), chart.GetProperty("series").EnumerateArray().Select(trace =>
                        new ChartTrace(trace.GetProperty("name").GetString()!,
                            trace.GetProperty("x").EnumerateArray().Select(x => x.GetDouble()).ToArray(),
                            trace.GetProperty("y").EnumerateArray().Select(y => y.GetDouble()).ToArray())).ToArray())).ToArray();
                ShowCharts(charts);
                break;
            case "waveform":
                var channels = data.EnumerateArray().Select(x => new WaveformSeries(
                    x.GetProperty("channel").GetString()!,
                    x.GetProperty("time").EnumerateArray().Select(v => v.GetDouble()).ToArray(),
                    x.GetProperty("value").EnumerateArray().Select(v => v.GetDouble()).ToArray(),
                    x.GetProperty("samples").GetInt32(),
                    x.GetProperty("minimum").GetDouble(), x.GetProperty("maximum").GetDouble())).ToList();
                ShowWaveforms(channels);
                break;
            case "user": Append(data.GetString() ?? "", "You"); break;
            case "assistant_delta": AppendDelta(data.GetString() ?? ""); break;
            case "assistant_end": FinishStream(data.GetString() ?? ""); break;
            case "assistant": Append(data.GetString() ?? "", "Assistant"); break;
            case "tool": AddTool(data.GetString() ?? "Tool"); break;
            case "artifact": if (RunArtifact.Parse(data) is RunArtifact artifact) AddArtifact(artifact); break;
            case "artifact_preview": if (RunPreview.Parse(data) is RunPreview preview) _conversation.Preview(preview); break;
            case "result": Append(data.ValueKind == JsonValueKind.String ? data.GetString() ?? "" : "A structured result is available in the workspace."); break;
            case "status": StatusText.Text = data.GetString() ?? "Working…"; break;
            case "error": _operationError = true; Append(data.GetString() ?? "Operation failed.", "Error"); Notify("The operation reported an error. See the conversation for details.", InfoBarSeverity.Error); break;
        }
    }

}
