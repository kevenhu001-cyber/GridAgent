using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Xml.Linq;

namespace GridAgent.Windows;

internal sealed class ScriptReviewWindow : Window
{
    public ScriptReviewWindow(string source)
    {
        Title = "Review Python source before sandbox execution";
        Width = 850; Height = 650; MinWidth = 500; MinHeight = 350;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        var layout = new DockPanel { Margin = new Thickness(20) };
        var warning = new TextBlock { Text = "Review the entire script. It will run in Windows Sandbox with network disabled. " +
            "Only a new output folder is writable. Outputs are untrusted; no automatic result import.",
            TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 0, 0, 12) };
        DockPanel.SetDock(warning, Dock.Top); layout.Children.Add(warning);
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
        var cancel = new Button { Content = "Cancel", IsCancel = true };
        var run = new Button { Content = "Approve and launch sandbox" };
        run.Click += (_, _) => DialogResult = true;
        buttons.Children.Add(cancel); buttons.Children.Add(run);
        DockPanel.SetDock(buttons, Dock.Bottom); layout.Children.Add(buttons);
        layout.Children.Add(new TextBox { Text = source, IsReadOnly = true, FontFamily = new FontFamily("Consolas"),
            AcceptsReturn = true, VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Auto });
        Content = layout;
    }
}

internal static class SandboxRunner
{
    public static string Launch(string workspace, string approvedSource)
    {
        var executable = Path.Combine(Environment.SystemDirectory, "WindowsSandbox.exe");
        var runtime = Path.Combine(AppContext.BaseDirectory, "runtime");
        if (!File.Exists(executable) || !File.Exists(Path.Combine(runtime, "python.exe")))
            throw new InvalidOperationException("Windows Sandbox or private Python is unavailable.");
        var folder = Path.Combine(workspace, "sandbox-jobs", Guid.NewGuid().ToString("N"));
        var input = Path.Combine(folder, "input");
        var output = Path.Combine(folder, "output");
        Directory.CreateDirectory(input); Directory.CreateDirectory(output);
        File.WriteAllText(Path.Combine(input, "script.py"), approvedSource, new UTF8Encoding(false));
        // Copy the exact reviewed string, never reread a potentially replaced file.
        File.WriteAllText(Path.Combine(input, "launch.cmd"),
            "@echo off\r\ncd /d C:\\GridAgentOutput\r\nset PYTHONNOUSERSITE=1\r\n" +
            "set OMP_NUM_THREADS=1\r\nset OPENBLAS_NUM_THREADS=1\r\n" +
            "C:\\GridAgentRuntime\\python.exe -I -B C:\\GridAgentInput\\script.py > stdout.log 2>&1\r\n" +
            "echo %errorlevel% > exit-code.txt\r\n", Encoding.ASCII);
        XElement Map(string host, string guest, bool readOnly) =>
            new("MappedFolder", new XElement("HostFolder", host), new XElement("SandboxFolder", guest),
                new XElement("ReadOnly", readOnly ? "true" : "false"));
        var config = new XElement("Configuration",
            new XElement("Networking", "Disable"), new XElement("VGpu", "Disable"),
            new XElement("ClipboardRedirection", "Disable"), new XElement("PrinterRedirection", "Disable"),
            new XElement("AudioInput", "Disable"), new XElement("VideoInput", "Disable"),
            new XElement("MemoryInMB", 4096),
            new XElement("MappedFolders", Map(runtime, @"C:\GridAgentRuntime", true),
                         Map(input, @"C:\GridAgentInput", true), Map(output, @"C:\GridAgentOutput", false)),
            new XElement("LogonCommand", new XElement("Command", @"cmd.exe /c C:\GridAgentInput\launch.cmd")));
        var path = Path.Combine(folder, "research.wsb");
        config.Save(path);
        var start = new ProcessStartInfo(executable) { UseShellExecute = false };
        start.ArgumentList.Add(path);
        using var process = Process.Start(start) ?? throw new InvalidOperationException("Sandbox startup failed.");
        return output;
    }
}
