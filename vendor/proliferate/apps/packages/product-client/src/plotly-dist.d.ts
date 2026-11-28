declare module "plotly.js-dist-min" {
  const plotly: {
    newPlot(element: HTMLElement, traces: unknown[], layout: unknown, config: unknown): Promise<unknown>;
    purge(element: HTMLElement): void;
    Plots: {resize(element: HTMLElement): Promise<unknown>};
  };
  export default plotly;
}
