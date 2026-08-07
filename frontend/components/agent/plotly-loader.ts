// Plotly 加载器 — 适配 plotly.js-dist-min（项目安装的包）
// react-plotly.js 默认引用 plotly.js/dist/plotly，需通过 factory 注入
import createPlotlyComponent from 'react-plotly.js/factory';
import Plotly from 'plotly.js-dist-min';

const Plot = createPlotlyComponent(Plotly);

export default Plot;
