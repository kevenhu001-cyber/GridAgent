using System.Reflection;

namespace GridAgent.Windows;

internal static class ProductInfo
{
    public const string Name = "GridAgent";
    public const string Developer = "TopoDrive";
    public const string LeadDeveloper = "Adex Hu";
    public const string License = "GPL-3.0-or-later";
    public const string Description = "AI-assisted power system research";
    public static string Version => typeof(ProductInfo).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion.Split('+')[0] ?? "0.1.0";
    public static string Distribution => AppDataPaths.IsPackaged
        ? $"MSIX · {global::Windows.ApplicationModel.Package.Current.Id.Version.Major}.{global::Windows.ApplicationModel.Package.Current.Id.Version.Minor}.{global::Windows.ApplicationModel.Package.Current.Id.Version.Build}.{global::Windows.ApplicationModel.Package.Current.Id.Version.Revision}"
        : "Portable desktop";
}
