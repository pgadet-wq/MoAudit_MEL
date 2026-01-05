import React, { useState, useEffect, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { AlertTriangle, CheckCircle, XCircle, AlertCircle, Filter, Search, Download, ChevronDown, ChevronUp, FileText, Clock, TrendingUp } from 'lucide-react';

// Sample data - In production, this would come from the API
const sampleAuditData = {
  run_id: "20260102_143052",
  mel_document: "Air_France_A320_MEL.pdf",
  mmel_document: "A320_MMEL_Rev42.pdf",
  audit_timestamp: "2026-01-02T14:30:52",
  summary: {
    total: 487,
    compliant: 412,
    more_restrictive: 35,
    less_restrictive: 8,
    missing_in_mel: 22,
    missing_in_mmel: 5,
    other_deviations: 5,
    hitl_required: 40,
    compliance_rate: 91.78
  },
  severity_breakdown: {
    critical: 8,
    high: 15,
    medium: 12,
    warning: 22,
    info: 430
  },
  comparisons: [
    {
      mel_item_id: "24|24-10-01",
      mmel_item_id: "24|24-10-01",
      ata_chapter: "24",
      item_number: "24-10-01",
      item_description: "Main Battery",
      verdict: "LESS_RESTRICTIVE",
      severity: "critical",
      mel_category: "B",
      mmel_category: "A",
      mel_remarks: "May be inoperative",
      mmel_remarks: "Go item - must be operative",
      hitl_reason: "CRITICAL: MEL less restrictive than MMEL"
    },
    {
      mel_item_id: "21|21-51-01",
      mmel_item_id: "21|21-51-01",
      ata_chapter: "21",
      item_number: "21-51-01",
      item_description: "Air Conditioning Pack",
      verdict: "COMPLIANT",
      severity: "info",
      mel_category: "C",
      mmel_category: "C",
      mel_remarks: "(O) May be inoperative provided remaining pack operates normally",
      mmel_remarks: "(O) May be inoperative provided remaining pack operates normally"
    },
    {
      mel_item_id: "32|32-40-01",
      mmel_item_id: "32|32-40-01",
      ata_chapter: "32",
      item_number: "32-40-01",
      item_description: "Nose Wheel Steering System",
      verdict: "MORE_RESTRICTIVE",
      severity: "info",
      mel_category: "B",
      mmel_category: "C",
      mel_remarks: "(M) Requires maintenance before dispatch",
      mmel_remarks: "May be inoperative"
    },
    {
      mel_item_id: "",
      mmel_item_id: "34|34-20-01",
      ata_chapter: "34",
      item_number: "34-20-01",
      item_description: "Weather Radar System",
      verdict: "MISSING_IN_MEL",
      severity: "warning",
      mel_category: "",
      mmel_category: "C",
      hitl_reason: "MMEL item not found in MEL - verify if equipment installed"
    },
    {
      mel_item_id: "27|27-30-01",
      mmel_item_id: "27|27-30-01",
      ata_chapter: "27",
      item_number: "27-30-01",
      item_description: "Aileron Trim System",
      verdict: "CATEGORY_MISMATCH",
      severity: "high",
      mel_category: "C",
      mmel_category: "B",
      hitl_reason: "Category deviation requires review"
    },
    {
      mel_item_id: "29|29-10-01",
      mmel_item_id: "29|29-10-01",
      ata_chapter: "29",
      item_number: "29-10-01",
      item_description: "Hydraulic System Pressure Indicator",
      verdict: "LESS_RESTRICTIVE",
      severity: "critical",
      mel_category: "D",
      mmel_category: "C",
      mel_remarks: "",
      mmel_remarks: "10 days repair interval",
      mel_repair_interval: "",
      mmel_repair_interval: "10 days"
    }
  ]
};

// Severity configurations
const severityConfig = {
  critical: { color: '#DC2626', bg: '#FEE2E2', icon: XCircle, label: 'Critical' },
  high: { color: '#EA580C', bg: '#FFEDD5', icon: AlertTriangle, label: 'High' },
  medium: { color: '#D97706', bg: '#FEF3C7', icon: AlertCircle, label: 'Medium' },
  warning: { color: '#CA8A04', bg: '#FEF9C3', icon: AlertCircle, label: 'Warning' },
  info: { color: '#16A34A', bg: '#DCFCE7', icon: CheckCircle, label: 'Info' }
};

const verdictConfig = {
  COMPLIANT: { color: '#16A34A', label: 'Conforme', icon: '✓' },
  MORE_RESTRICTIVE: { color: '#2563EB', label: 'Plus Restrictif', icon: '↑' },
  LESS_RESTRICTIVE: { color: '#DC2626', label: 'Moins Restrictif', icon: '↓' },
  MISSING_IN_MEL: { color: '#EA580C', label: 'Absent MEL', icon: '⚠' },
  MISSING_IN_MMEL: { color: '#6B7280', label: 'Absent MMEL', icon: '○' },
  CATEGORY_MISMATCH: { color: '#7C3AED', label: 'Écart Catégorie', icon: '≠' },
  REMARKS_DEVIATION: { color: '#0891B2', label: 'Écart Remarques', icon: '~' }
};

// Summary Card Component
const SummaryCard = ({ title, value, subtitle, icon: Icon, color, trend }) => (
  <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100 hover:shadow-md transition-shadow">
    <div className="flex items-start justify-between">
      <div>
        <p className="text-sm text-gray-500 font-medium">{title}</p>
        <p className="text-3xl font-bold mt-1" style={{ color }}>{value}</p>
        {subtitle && <p className="text-xs text-gray-400 mt-1">{subtitle}</p>}
      </div>
      <div className="p-3 rounded-lg" style={{ backgroundColor: `${color}15` }}>
        <Icon size={24} style={{ color }} />
      </div>
    </div>
    {trend && (
      <div className="mt-3 flex items-center text-xs">
        <TrendingUp size={14} className="mr-1" style={{ color: trend > 0 ? '#16A34A' : '#DC2626' }} />
        <span style={{ color: trend > 0 ? '#16A34A' : '#DC2626' }}>{Math.abs(trend)}% vs précédent</span>
      </div>
    )}
  </div>
);

// Verdict Badge Component
const VerdictBadge = ({ verdict }) => {
  const config = verdictConfig[verdict] || { color: '#6B7280', label: verdict, icon: '?' };
  return (
    <span 
      className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold"
      style={{ backgroundColor: `${config.color}15`, color: config.color }}
    >
      <span className="mr-1">{config.icon}</span>
      {config.label}
    </span>
  );
};

// Severity Badge Component
const SeverityBadge = ({ severity }) => {
  const config = severityConfig[severity] || severityConfig.info;
  const Icon = config.icon;
  return (
    <span 
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{ backgroundColor: config.bg, color: config.color }}
    >
      <Icon size={12} className="mr-1" />
      {config.label}
    </span>
  );
};

// Expandable Row Component
const ComparisonRow = ({ item, isExpanded, onToggle }) => {
  const severityConf = severityConfig[item.severity] || severityConfig.info;
  
  return (
    <>
      <tr 
        className={`hover:bg-gray-50 cursor-pointer transition-colors ${isExpanded ? 'bg-gray-50' : ''}`}
        onClick={onToggle}
      >
        <td className="px-4 py-3">
          <div className="flex items-center">
            {isExpanded ? <ChevronUp size={16} className="text-gray-400 mr-2" /> : <ChevronDown size={16} className="text-gray-400 mr-2" />}
            <span className="font-mono text-sm font-medium text-gray-900">{item.ata_chapter}</span>
          </div>
        </td>
        <td className="px-4 py-3 font-mono text-sm">{item.item_number}</td>
        <td className="px-4 py-3">
          <div className="max-w-xs truncate text-sm text-gray-700" title={item.item_description}>
            {item.item_description}
          </div>
        </td>
        <td className="px-4 py-3 text-center">
          <span className="font-bold text-lg" style={{ color: item.mel_category !== item.mmel_category ? '#DC2626' : '#374151' }}>
            {item.mel_category || '-'}
          </span>
        </td>
        <td className="px-4 py-3 text-center">
          <span className="font-bold text-lg text-gray-700">
            {item.mmel_category || '-'}
          </span>
        </td>
        <td className="px-4 py-3"><VerdictBadge verdict={item.verdict} /></td>
        <td className="px-4 py-3"><SeverityBadge severity={item.severity} /></td>
      </tr>
      {isExpanded && (
        <tr className="bg-gray-50">
          <td colSpan="7" className="px-6 py-4">
            <div className="grid grid-cols-2 gap-6">
              <div className="space-y-3">
                <h4 className="font-semibold text-sm text-blue-700 flex items-center">
                  <FileText size={14} className="mr-1" /> MEL
                </h4>
                <div className="bg-white p-3 rounded-lg border border-blue-100">
                  <p className="text-xs text-gray-500">Catégorie</p>
                  <p className="font-bold text-lg text-blue-700">{item.mel_category || '-'}</p>
                </div>
                <div className="bg-white p-3 rounded-lg border border-blue-100">
                  <p className="text-xs text-gray-500">Remarques</p>
                  <p className="text-sm text-gray-700">{item.mel_remarks || 'Aucune remarque'}</p>
                </div>
                {item.mel_repair_interval && (
                  <div className="bg-white p-3 rounded-lg border border-blue-100">
                    <p className="text-xs text-gray-500">Intervalle de réparation</p>
                    <p className="text-sm font-medium">{item.mel_repair_interval}</p>
                  </div>
                )}
              </div>
              <div className="space-y-3">
                <h4 className="font-semibold text-sm text-green-700 flex items-center">
                  <FileText size={14} className="mr-1" /> MMEL (Référence)
                </h4>
                <div className="bg-white p-3 rounded-lg border border-green-100">
                  <p className="text-xs text-gray-500">Catégorie</p>
                  <p className="font-bold text-lg text-green-700">{item.mmel_category || '-'}</p>
                </div>
                <div className="bg-white p-3 rounded-lg border border-green-100">
                  <p className="text-xs text-gray-500">Remarques</p>
                  <p className="text-sm text-gray-700">{item.mmel_remarks || 'Aucune remarque'}</p>
                </div>
                {item.mmel_repair_interval && (
                  <div className="bg-white p-3 rounded-lg border border-green-100">
                    <p className="text-xs text-gray-500">Intervalle de réparation</p>
                    <p className="text-sm font-medium">{item.mmel_repair_interval}</p>
                  </div>
                )}
              </div>
            </div>
            {item.hitl_reason && (
              <div className="mt-4 p-3 rounded-lg" style={{ backgroundColor: severityConf.bg }}>
                <p className="text-sm font-medium" style={{ color: severityConf.color }}>
                  <AlertTriangle size={14} className="inline mr-1" />
                  {item.hitl_reason}
                </p>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
};

// Main Dashboard Component
export default function MoAMELDashboard() {
  const [data, setData] = useState(sampleAuditData);
  const [searchTerm, setSearchTerm] = useState('');
  const [severityFilter, setSeverityFilter] = useState('all');
  const [verdictFilter, setVerdictFilter] = useState('all');
  const [expandedRows, setExpandedRows] = useState(new Set());
  const [sortConfig, setSortConfig] = useState({ key: 'severity', direction: 'asc' });

  // Severity order for sorting
  const severityOrder = { critical: 0, high: 1, medium: 2, warning: 3, info: 4 };

  // Filter and sort comparisons
  const filteredComparisons = useMemo(() => {
    let filtered = [...data.comparisons];
    
    // Search filter
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      filtered = filtered.filter(item => 
        item.ata_chapter?.toLowerCase().includes(term) ||
        item.item_number?.toLowerCase().includes(term) ||
        item.item_description?.toLowerCase().includes(term)
      );
    }
    
    // Severity filter
    if (severityFilter !== 'all') {
      filtered = filtered.filter(item => item.severity === severityFilter);
    }
    
    // Verdict filter
    if (verdictFilter !== 'all') {
      filtered = filtered.filter(item => item.verdict === verdictFilter);
    }
    
    // Sort
    filtered.sort((a, b) => {
      if (sortConfig.key === 'severity') {
        const diff = severityOrder[a.severity] - severityOrder[b.severity];
        return sortConfig.direction === 'asc' ? diff : -diff;
      }
      if (sortConfig.key === 'ata_chapter') {
        const diff = a.ata_chapter.localeCompare(b.ata_chapter);
        return sortConfig.direction === 'asc' ? diff : -diff;
      }
      return 0;
    });
    
    return filtered;
  }, [data.comparisons, searchTerm, severityFilter, verdictFilter, sortConfig]);

  // Chart data
  const verdictChartData = useMemo(() => [
    { name: 'Conforme', value: data.summary.compliant, color: '#16A34A' },
    { name: 'Plus Restrictif', value: data.summary.more_restrictive, color: '#2563EB' },
    { name: 'Moins Restrictif', value: data.summary.less_restrictive, color: '#DC2626' },
    { name: 'Absent MEL', value: data.summary.missing_in_mel, color: '#EA580C' },
    { name: 'Absent MMEL', value: data.summary.missing_in_mmel, color: '#6B7280' },
    { name: 'Autres', value: data.summary.other_deviations, color: '#7C3AED' }
  ].filter(d => d.value > 0), [data.summary]);

  const severityChartData = useMemo(() => [
    { name: 'Critique', value: data.severity_breakdown.critical, color: '#DC2626' },
    { name: 'Élevé', value: data.severity_breakdown.high, color: '#EA580C' },
    { name: 'Moyen', value: data.severity_breakdown.medium, color: '#D97706' },
    { name: 'Attention', value: data.severity_breakdown.warning, color: '#CA8A04' },
    { name: 'Info', value: data.severity_breakdown.info, color: '#16A34A' }
  ], [data.severity_breakdown]);

  const toggleRow = (id) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedRows(newExpanded);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              <div className="bg-gradient-to-br from-red-600 to-red-700 text-white px-4 py-2 rounded-lg font-bold">
                MoA_MEL
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">Audit MEL/MMEL</h1>
                <p className="text-sm text-gray-500">Rapport d'écarts - {new Date(data.audit_timestamp).toLocaleDateString('fr-FR')}</p>
              </div>
            </div>
            <div className="flex items-center space-x-3">
              <span className="text-xs bg-gray-100 px-2 py-1 rounded font-mono">
                Run #{data.run_id}
              </span>
              <button className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
                <Download size={16} className="mr-2" />
                Export PDF
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* Document Info */}
        <div className="bg-white rounded-xl p-4 mb-6 border border-gray-200 flex items-center justify-between">
          <div className="flex items-center space-x-8">
            <div className="flex items-center">
              <div className="w-2 h-2 bg-blue-500 rounded-full mr-2"></div>
              <span className="text-sm text-gray-600">MEL:</span>
              <span className="ml-2 font-medium">{data.mel_document}</span>
            </div>
            <div className="flex items-center">
              <div className="w-2 h-2 bg-green-500 rounded-full mr-2"></div>
              <span className="text-sm text-gray-600">MMEL:</span>
              <span className="ml-2 font-medium">{data.mmel_document}</span>
            </div>
          </div>
          <div className="flex items-center text-sm text-gray-500">
            <Clock size={14} className="mr-1" />
            {new Date(data.audit_timestamp).toLocaleString('fr-FR')}
          </div>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-5 gap-4 mb-8">
          <SummaryCard 
            title="Items Analysés" 
            value={data.summary.total}
            icon={FileText}
            color="#374151"
          />
          <SummaryCard 
            title="Taux Conformité" 
            value={`${data.summary.compliance_rate}%`}
            subtitle={`${data.summary.compliant + data.summary.more_restrictive} items OK`}
            icon={CheckCircle}
            color="#16A34A"
            trend={2.3}
          />
          <SummaryCard 
            title="Écarts Critiques" 
            value={data.severity_breakdown.critical}
            subtitle="Action immédiate requise"
            icon={XCircle}
            color="#DC2626"
          />
          <SummaryCard 
            title="Review HITL" 
            value={data.summary.hitl_required}
            subtitle="En attente validation"
            icon={AlertTriangle}
            color="#EA580C"
          />
          <SummaryCard 
            title="SLA 48h" 
            value={data.severity_breakdown.critical + data.severity_breakdown.high}
            subtitle="Items prioritaires"
            icon={Clock}
            color="#7C3AED"
          />
        </div>

        {/* Charts */}
        <div className="grid grid-cols-2 gap-6 mb-8">
          <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
            <h3 className="font-semibold text-gray-900 mb-4">Distribution des Verdicts</h3>
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={verdictChartData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  dataKey="value"
                  label={({ name, value }) => `${name}: ${value}`}
                >
                  {verdictChartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
            <h3 className="font-semibold text-gray-900 mb-4">Distribution par Sévérité</h3>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={severityChartData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" />
                <YAxis type="category" dataKey="name" width={80} />
                <Tooltip />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {severityChartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Filters */}
        <div className="bg-white rounded-xl p-4 mb-6 shadow-sm border border-gray-100">
          <div className="flex items-center space-x-4">
            <div className="flex items-center flex-1 bg-gray-50 rounded-lg px-3 py-2">
              <Search size={18} className="text-gray-400 mr-2" />
              <input
                type="text"
                placeholder="Rechercher par ATA, Item ou Description..."
                className="bg-transparent flex-1 outline-none text-sm"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>
            <div className="flex items-center space-x-2">
              <Filter size={18} className="text-gray-400" />
              <select
                className="bg-gray-50 rounded-lg px-3 py-2 text-sm outline-none border-none"
                value={severityFilter}
                onChange={(e) => setSeverityFilter(e.target.value)}
              >
                <option value="all">Toutes Sévérités</option>
                <option value="critical">Critique</option>
                <option value="high">Élevé</option>
                <option value="medium">Moyen</option>
                <option value="warning">Attention</option>
                <option value="info">Info</option>
              </select>
              <select
                className="bg-gray-50 rounded-lg px-3 py-2 text-sm outline-none border-none"
                value={verdictFilter}
                onChange={(e) => setVerdictFilter(e.target.value)}
              >
                <option value="all">Tous Verdicts</option>
                <option value="COMPLIANT">Conforme</option>
                <option value="MORE_RESTRICTIVE">Plus Restrictif</option>
                <option value="LESS_RESTRICTIVE">Moins Restrictif</option>
                <option value="MISSING_IN_MEL">Absent MEL</option>
                <option value="MISSING_IN_MMEL">Absent MMEL</option>
                <option value="CATEGORY_MISMATCH">Écart Catégorie</option>
              </select>
            </div>
            <span className="text-sm text-gray-500">
              {filteredComparisons.length} / {data.comparisons.length} items
            </span>
          </div>
        </div>

        {/* Comparisons Table */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  ATA
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Item
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Description
                </th>
                <th className="px-4 py-3 text-center text-xs font-semibold text-blue-600 uppercase tracking-wider">
                  MEL Cat.
                </th>
                <th className="px-4 py-3 text-center text-xs font-semibold text-green-600 uppercase tracking-wider">
                  MMEL Cat.
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Verdict
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Sévérité
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filteredComparisons.map((item, index) => (
                <ComparisonRow
                  key={`${item.mel_item_id || item.mmel_item_id}-${index}`}
                  item={item}
                  isExpanded={expandedRows.has(`${item.mel_item_id || item.mmel_item_id}-${index}`)}
                  onToggle={() => toggleRow(`${item.mel_item_id || item.mmel_item_id}-${index}`)}
                />
              ))}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <footer className="mt-8 text-center text-sm text-gray-500">
          <p>MoA_MEL Audit PoC — WingMate™ by OPS Insight</p>
          <p className="mt-1">Généré avec Mistral AI 🇫🇷 • Infrastructure Scaleway</p>
        </footer>
      </main>
    </div>
  );
}
