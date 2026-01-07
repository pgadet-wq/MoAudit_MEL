/**
 * MoA_MEL Audit - React SPA
 * 6-Step Wizard with Interactive Validation
 */

const { useState, useEffect, useCallback, useMemo } = React;

// ============== API Client ==============

const API_BASE = '';

const api = {
    async request(method, endpoint, data = null) {
        const options = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (data && method !== 'GET') {
            options.body = JSON.stringify(data);
        }
        const response = await fetch(`${API_BASE}${endpoint}`, options);
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Request failed' }));
            throw new Error(error.detail || 'Request failed');
        }
        return response.json();
    },

    async uploadFile(endpoint, file) {
        const formData = new FormData();
        formData.append('file', file);
        const response = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
            throw new Error(error.detail || 'Upload failed');
        }
        return response.json();
    },

    // Sessions
    createSession: (data) => api.request('POST', '/api/sessions', data),
    getSessions: () => api.request('GET', '/api/sessions'),
    getSession: (id) => api.request('GET', `/api/sessions/${id}`),
    updateSession: (id, data) => api.request('PUT', `/api/sessions/${id}`, data),
    deleteSession: (id) => api.request('DELETE', `/api/sessions/${id}`),

    // Step 1 & 2 - MMEL
    uploadMMEL: (sessionId, file) => api.uploadFile(`/api/sessions/${sessionId}/step1/upload`, file),
    parseMMEL: (sessionId) => api.request('POST', `/api/sessions/${sessionId}/step1/parse`),
    getMMELItems: (sessionId, params = '') => api.request('GET', `/api/sessions/${sessionId}/step2/items${params}`),
    validateMMEL: (sessionId, data) => api.request('POST', `/api/sessions/${sessionId}/step2/validate`, data),

    // Step 3 & 4 - MEL
    uploadMEL: (sessionId, file) => api.uploadFile(`/api/sessions/${sessionId}/step3/upload`, file),
    parseMEL: (sessionId) => api.request('POST', `/api/sessions/${sessionId}/step3/parse`),
    getMELItems: (sessionId, params = '') => api.request('GET', `/api/sessions/${sessionId}/step4/items${params}`),
    validateMEL: (sessionId, data) => api.request('POST', `/api/sessions/${sessionId}/step4/validate`, data),

    // Items
    updateItem: (sessionId, itemId, data) => api.request('PUT', `/api/sessions/${sessionId}/items/${itemId}`, data),
    addAnnotation: (sessionId, itemId, data) => api.request('POST', `/api/sessions/${sessionId}/items/${itemId}/annotations`, data),
    deleteAnnotation: (sessionId, annotationId) => api.request('DELETE', `/api/sessions/${sessionId}/annotations/${annotationId}`),

    // Step 5 & 6 - Audit
    runAudit: (sessionId) => api.request('POST', `/api/sessions/${sessionId}/step5/run`),
    getResults: (sessionId, params = '') => api.request('GET', `/api/sessions/${sessionId}/step6/results${params}`),
    getSummary: (sessionId) => api.request('GET', `/api/sessions/${sessionId}/step6/summary`),
    validateHITL: (sessionId, resultId, data) => api.request('POST', `/api/sessions/${sessionId}/step6/hitl/${resultId}`, data),
    completeAudit: (sessionId, data) => api.request('POST', `/api/sessions/${sessionId}/step6/complete`, data),
};


// ============== Components ==============

// Step indicator
const StepIndicator = ({ currentStep, steps }) => (
    <div className="flex items-center justify-between mb-8">
        {steps.map((step, index) => (
            <div key={index} className="flex items-center">
                <div className={`flex items-center justify-center w-10 h-10 rounded-full border-2
                    ${index + 1 < currentStep ? 'bg-green-500 border-green-500 text-white' :
                      index + 1 === currentStep ? 'bg-blue-500 border-blue-500 text-white' :
                      'bg-white border-gray-300 text-gray-500'}`}>
                    {index + 1 < currentStep ? (
                        <i className="fas fa-check"></i>
                    ) : (
                        <span>{index + 1}</span>
                    )}
                </div>
                <div className="ml-2 hidden md:block">
                    <p className={`text-sm font-medium ${index + 1 === currentStep ? 'text-blue-600' : 'text-gray-500'}`}>
                        {step.title}
                    </p>
                </div>
                {index < steps.length - 1 && (
                    <div className={`w-12 h-1 mx-2 ${index + 1 < currentStep ? 'bg-green-500' : 'bg-gray-300'}`}></div>
                )}
            </div>
        ))}
    </div>
);


// File Upload Component
const FileUpload = ({ onUpload, accept = ".pdf", label, uploading }) => {
    const [dragActive, setDragActive] = useState(false);
    const [file, setFile] = useState(null);

    const handleDrag = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(e.type === 'dragenter' || e.type === 'dragover');
    };

    const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            setFile(e.dataTransfer.files[0]);
        }
    };

    const handleChange = (e) => {
        if (e.target.files && e.target.files[0]) {
            setFile(e.target.files[0]);
        }
    };

    const handleUpload = () => {
        if (file) {
            onUpload(file);
        }
    };

    return (
        <div className="w-full">
            <div
                className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors
                    ${dragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}`}
                onDragEnter={handleDrag}
                onDragLeave={handleDrag}
                onDragOver={handleDrag}
                onDrop={handleDrop}
            >
                <i className="fas fa-cloud-upload-alt text-4xl text-gray-400 mb-4"></i>
                <p className="text-lg mb-2">{label}</p>
                <p className="text-sm text-gray-500 mb-4">Glissez-déposez ou cliquez pour sélectionner</p>
                <input
                    type="file"
                    accept={accept}
                    onChange={handleChange}
                    className="hidden"
                    id="file-upload"
                />
                <label htmlFor="file-upload" className="cursor-pointer text-blue-500 hover:text-blue-700">
                    Parcourir les fichiers
                </label>
            </div>
            {file && (
                <div className="mt-4 p-4 bg-gray-50 rounded-lg flex items-center justify-between">
                    <div className="flex items-center">
                        <i className="fas fa-file-pdf text-red-500 text-2xl mr-3"></i>
                        <div>
                            <p className="font-medium">{file.name}</p>
                            <p className="text-sm text-gray-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                        </div>
                    </div>
                    <button
                        onClick={handleUpload}
                        disabled={uploading}
                        className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50"
                    >
                        {uploading ? (
                            <><i className="fas fa-spinner fa-spin mr-2"></i>Envoi...</>
                        ) : (
                            <><i className="fas fa-upload mr-2"></i>Envoyer</>
                        )}
                    </button>
                </div>
            )}
        </div>
    );
};


// Editable Cell Component
const EditableCell = ({ value, field, itemId, onSave, type = "text" }) => {
    const [editing, setEditing] = useState(false);
    const [editValue, setEditValue] = useState(value);

    const handleSave = () => {
        if (editValue !== value) {
            onSave(itemId, field, editValue);
        }
        setEditing(false);
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter') handleSave();
        if (e.key === 'Escape') {
            setEditValue(value);
            setEditing(false);
        }
    };

    if (editing) {
        return (
            <div className="flex items-center">
                {type === "select" ? (
                    <select
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={handleSave}
                        className="border rounded px-2 py-1 text-sm w-full"
                        autoFocus
                    >
                        {["A", "B", "C", "D"].map(cat => (
                            <option key={cat} value={cat}>{cat}</option>
                        ))}
                    </select>
                ) : type === "textarea" ? (
                    <textarea
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={handleSave}
                        onKeyDown={handleKeyDown}
                        className="border rounded px-2 py-1 text-sm w-full"
                        rows={3}
                        autoFocus
                    />
                ) : (
                    <input
                        type="text"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={handleSave}
                        onKeyDown={handleKeyDown}
                        className="border rounded px-2 py-1 text-sm w-full"
                        autoFocus
                    />
                )}
            </div>
        );
    }

    return (
        <div
            className="cursor-pointer hover:bg-yellow-50 p-1 rounded group"
            onClick={() => setEditing(true)}
            title="Cliquer pour modifier"
        >
            <span>{value || '-'}</span>
            <i className="fas fa-edit text-gray-400 ml-1 opacity-0 group-hover:opacity-100"></i>
        </div>
    );
};


// Annotation Component
const AnnotationBadge = ({ annotations, itemId, sessionId, onAdd, onDelete }) => {
    const [showPopup, setShowPopup] = useState(false);
    const [newAnnotation, setNewAnnotation] = useState('');
    const [annotationType, setAnnotationType] = useState('comment');

    const handleAdd = async () => {
        if (newAnnotation.trim()) {
            await onAdd(itemId, {
                content: newAnnotation,
                annotation_type: annotationType
            });
            setNewAnnotation('');
            setShowPopup(false);
        }
    };

    const typeColors = {
        comment: 'bg-blue-100 text-blue-800',
        warning: 'bg-yellow-100 text-yellow-800',
        question: 'bg-purple-100 text-purple-800',
        note: 'bg-green-100 text-green-800'
    };

    return (
        <div className="relative">
            <button
                onClick={() => setShowPopup(!showPopup)}
                className={`flex items-center px-2 py-1 rounded text-sm
                    ${annotations.length > 0 ? 'bg-yellow-100 text-yellow-800' : 'bg-gray-100 text-gray-600'}`}
            >
                <i className="fas fa-comment mr-1"></i>
                {annotations.length}
            </button>

            {showPopup && (
                <div className="absolute z-50 right-0 mt-2 w-80 bg-white rounded-lg shadow-xl border p-4">
                    <h4 className="font-medium mb-3">Annotations</h4>

                    {/* Existing annotations */}
                    {annotations.length > 0 && (
                        <div className="mb-3 max-h-40 overflow-y-auto">
                            {annotations.map((ann, idx) => (
                                <div key={idx} className={`p-2 rounded mb-2 ${typeColors[ann.annotation_type]}`}>
                                    <div className="flex justify-between items-start">
                                        <span className="text-sm">{ann.content}</span>
                                        <button
                                            onClick={() => onDelete(ann.id)}
                                            className="text-red-500 hover:text-red-700 ml-2"
                                        >
                                            <i className="fas fa-times"></i>
                                        </button>
                                    </div>
                                    <p className="text-xs mt-1 opacity-70">
                                        {ann.author || 'Anonyme'} - {new Date(ann.created_at).toLocaleString('fr-FR')}
                                    </p>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Add new annotation */}
                    <div className="border-t pt-3">
                        <select
                            value={annotationType}
                            onChange={(e) => setAnnotationType(e.target.value)}
                            className="w-full border rounded px-2 py-1 text-sm mb-2"
                        >
                            <option value="comment">Commentaire</option>
                            <option value="warning">Avertissement</option>
                            <option value="question">Question</option>
                            <option value="note">Note</option>
                        </select>
                        <textarea
                            value={newAnnotation}
                            onChange={(e) => setNewAnnotation(e.target.value)}
                            placeholder="Ajouter une annotation..."
                            className="w-full border rounded px-2 py-1 text-sm"
                            rows={2}
                        />
                        <div className="flex justify-end mt-2 gap-2">
                            <button
                                onClick={() => setShowPopup(false)}
                                className="px-3 py-1 text-sm text-gray-600 hover:bg-gray-100 rounded"
                            >
                                Fermer
                            </button>
                            <button
                                onClick={handleAdd}
                                className="px-3 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600"
                            >
                                Ajouter
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};


// Items Table Component
const ItemsTable = ({ items, chapters, onUpdateItem, onAddAnnotation, onDeleteAnnotation, sessionId, selectedChapter, onChapterChange }) => {
    return (
        <div>
            {/* Chapter filter */}
            <div className="mb-4 flex items-center gap-4">
                <label className="font-medium">Chapitre ATA:</label>
                <select
                    value={selectedChapter}
                    onChange={(e) => onChapterChange(e.target.value)}
                    className="border rounded px-3 py-2"
                >
                    <option value="">Tous les chapitres</option>
                    {chapters.map(ch => (
                        <option key={ch.chapter} value={ch.chapter}>
                            ATA {ch.chapter} ({ch.count} items)
                        </option>
                    ))}
                </select>
                <span className="text-gray-500">{items.length} items affichés</span>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
                <table className="w-full border-collapse">
                    <thead>
                        <tr className="bg-gray-100">
                            <th className="border p-2 text-left text-sm">ATA</th>
                            <th className="border p-2 text-left text-sm">N° Item</th>
                            <th className="border p-2 text-left text-sm w-1/4">Description</th>
                            <th className="border p-2 text-center text-sm">Cat.</th>
                            <th className="border p-2 text-center text-sm">Inst.</th>
                            <th className="border p-2 text-center text-sm">Req.</th>
                            <th className="border p-2 text-left text-sm w-1/4">Remarques</th>
                            <th className="border p-2 text-center text-sm">Conf.</th>
                            <th className="border p-2 text-center text-sm">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items.map(item => (
                            <tr key={item.id} className={`hover:bg-gray-50 ${item.is_corrected ? 'bg-yellow-50' : ''}`}>
                                <td className="border p-2 text-sm">{item.ata_chapter}</td>
                                <td className="border p-2 text-sm">
                                    <EditableCell
                                        value={item.item_number}
                                        field="item_number"
                                        itemId={item.id}
                                        onSave={onUpdateItem}
                                    />
                                </td>
                                <td className="border p-2 text-sm">
                                    <EditableCell
                                        value={item.item_description}
                                        field="item_description"
                                        itemId={item.id}
                                        onSave={onUpdateItem}
                                        type="textarea"
                                    />
                                </td>
                                <td className="border p-2 text-center">
                                    <EditableCell
                                        value={item.category}
                                        field="category"
                                        itemId={item.id}
                                        onSave={onUpdateItem}
                                        type="select"
                                    />
                                </td>
                                <td className="border p-2 text-center text-sm">
                                    <EditableCell
                                        value={item.number_installed}
                                        field="number_installed"
                                        itemId={item.id}
                                        onSave={onUpdateItem}
                                    />
                                </td>
                                <td className="border p-2 text-center text-sm">
                                    <EditableCell
                                        value={item.number_required}
                                        field="number_required"
                                        itemId={item.id}
                                        onSave={onUpdateItem}
                                    />
                                </td>
                                <td className="border p-2 text-sm">
                                    <EditableCell
                                        value={item.remarks}
                                        field="remarks"
                                        itemId={item.id}
                                        onSave={onUpdateItem}
                                        type="textarea"
                                    />
                                </td>
                                <td className="border p-2 text-center">
                                    <span className={`px-2 py-1 rounded text-xs
                                        ${item.extraction_confidence >= 0.9 ? 'bg-green-100 text-green-800' :
                                          item.extraction_confidence >= 0.7 ? 'bg-yellow-100 text-yellow-800' :
                                          'bg-red-100 text-red-800'}`}>
                                        {Math.round(item.extraction_confidence * 100)}%
                                    </span>
                                </td>
                                <td className="border p-2 text-center">
                                    <AnnotationBadge
                                        annotations={item.annotations || []}
                                        itemId={item.id}
                                        sessionId={sessionId}
                                        onAdd={onAddAnnotation}
                                        onDelete={onDeleteAnnotation}
                                    />
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};


// Results Table Component
const ResultsTable = ({ results, onValidateHITL }) => {
    const verdictColors = {
        COMPLIANT: 'bg-green-100 text-green-800',
        MORE_RESTRICTIVE: 'bg-blue-100 text-blue-800',
        LESS_RESTRICTIVE: 'bg-red-100 text-red-800',
        MISSING_IN_MEL: 'bg-orange-100 text-orange-800',
        MISSING_IN_MMEL: 'bg-yellow-100 text-yellow-800'
    };

    const severityColors = {
        critical: 'bg-red-500 text-white',
        high: 'bg-orange-500 text-white',
        medium: 'bg-yellow-500 text-white',
        warning: 'bg-blue-500 text-white',
        info: 'bg-gray-400 text-white'
    };

    return (
        <div className="overflow-x-auto">
            <table className="w-full border-collapse">
                <thead>
                    <tr className="bg-gray-100">
                        <th className="border p-2 text-left text-sm">ATA</th>
                        <th className="border p-2 text-left text-sm">Item MEL</th>
                        <th className="border p-2 text-left text-sm">Item MMEL</th>
                        <th className="border p-2 text-left text-sm">Description</th>
                        <th className="border p-2 text-center text-sm">Cat. MEL</th>
                        <th className="border p-2 text-center text-sm">Cat. MMEL</th>
                        <th className="border p-2 text-center text-sm">Verdict</th>
                        <th className="border p-2 text-center text-sm">Sévérité</th>
                        <th className="border p-2 text-center text-sm">HITL</th>
                    </tr>
                </thead>
                <tbody>
                    {results.map(result => (
                        <tr key={result.id} className="hover:bg-gray-50">
                            <td className="border p-2 text-sm">{result.ata_chapter}</td>
                            <td className="border p-2 text-sm">{result.mel_item_number || '-'}</td>
                            <td className="border p-2 text-sm">{result.mmel_item_number || '-'}</td>
                            <td className="border p-2 text-sm max-w-xs truncate">{result.item_description}</td>
                            <td className="border p-2 text-center font-bold">{result.mel_category || '-'}</td>
                            <td className="border p-2 text-center font-bold">{result.mmel_category || '-'}</td>
                            <td className="border p-2 text-center">
                                <span className={`px-2 py-1 rounded text-xs ${verdictColors[result.verdict]}`}>
                                    {result.verdict}
                                </span>
                            </td>
                            <td className="border p-2 text-center">
                                <span className={`px-2 py-1 rounded text-xs ${severityColors[result.severity]}`}>
                                    {result.severity}
                                </span>
                            </td>
                            <td className="border p-2 text-center">
                                {result.requires_hitl && (
                                    <div>
                                        {result.hitl_status === 'pending' ? (
                                            <div className="flex gap-1 justify-center">
                                                <button
                                                    onClick={() => onValidateHITL(result.id, 'accepted')}
                                                    className="px-2 py-1 bg-green-500 text-white rounded text-xs hover:bg-green-600"
                                                    title="Accepter"
                                                >
                                                    <i className="fas fa-check"></i>
                                                </button>
                                                <button
                                                    onClick={() => onValidateHITL(result.id, 'rejected')}
                                                    className="px-2 py-1 bg-red-500 text-white rounded text-xs hover:bg-red-600"
                                                    title="Rejeter"
                                                >
                                                    <i className="fas fa-times"></i>
                                                </button>
                                            </div>
                                        ) : (
                                            <span className={`px-2 py-1 rounded text-xs
                                                ${result.hitl_status === 'accepted' ? 'bg-green-100 text-green-800' :
                                                  result.hitl_status === 'rejected' ? 'bg-red-100 text-red-800' :
                                                  'bg-yellow-100 text-yellow-800'}`}>
                                                {result.hitl_status}
                                            </span>
                                        )}
                                    </div>
                                )}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
};


// Summary Dashboard
const SummaryDashboard = ({ summary }) => {
    if (!summary) return null;

    const { summary: stats, by_severity, by_chapter, critical_items } = summary;

    return (
        <div className="space-y-6">
            {/* Overview Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-white p-4 rounded-lg shadow">
                    <p className="text-gray-500 text-sm">Total Comparaisons</p>
                    <p className="text-3xl font-bold">{stats.total_comparisons}</p>
                </div>
                <div className="bg-green-50 p-4 rounded-lg shadow">
                    <p className="text-green-600 text-sm">Conformes</p>
                    <p className="text-3xl font-bold text-green-600">{stats.compliant + stats.more_restrictive}</p>
                </div>
                <div className="bg-red-50 p-4 rounded-lg shadow">
                    <p className="text-red-600 text-sm">Moins Restrictifs</p>
                    <p className="text-3xl font-bold text-red-600">{stats.less_restrictive}</p>
                </div>
                <div className="bg-blue-50 p-4 rounded-lg shadow">
                    <p className="text-blue-600 text-sm">Taux Conformité</p>
                    <p className="text-3xl font-bold text-blue-600">{stats.compliance_rate}%</p>
                </div>
            </div>

            {/* Severity Breakdown */}
            <div className="bg-white p-4 rounded-lg shadow">
                <h3 className="font-medium mb-4">Répartition par Sévérité</h3>
                <div className="flex gap-4">
                    {Object.entries(by_severity).map(([severity, count]) => (
                        <div key={severity} className="flex items-center gap-2">
                            <span className={`w-3 h-3 rounded-full
                                ${severity === 'critical' ? 'bg-red-500' :
                                  severity === 'high' ? 'bg-orange-500' :
                                  severity === 'medium' ? 'bg-yellow-500' :
                                  severity === 'warning' ? 'bg-blue-500' : 'bg-gray-400'}`}></span>
                            <span className="text-sm">{severity}: {count}</span>
                        </div>
                    ))}
                </div>
            </div>

            {/* Critical Items */}
            {critical_items && critical_items.length > 0 && (
                <div className="bg-red-50 p-4 rounded-lg shadow border border-red-200">
                    <h3 className="font-medium text-red-800 mb-4">
                        <i className="fas fa-exclamation-triangle mr-2"></i>
                        Items Critiques ({critical_items.length})
                    </h3>
                    <div className="space-y-2">
                        {critical_items.map((item, idx) => (
                            <div key={idx} className="bg-white p-3 rounded border border-red-200">
                                <p className="font-medium">{item.mel_item_number || item.mmel_item_number}</p>
                                <p className="text-sm text-gray-600">{item.item_description}</p>
                                <p className="text-sm text-red-600 mt-1">{item.verdict}</p>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};


// Session History
const SessionHistory = ({ sessions, onSelect, onDelete, onCreate }) => (
    <div className="bg-white rounded-lg shadow p-6">
        <div className="flex justify-between items-center mb-4">
            <h2 className="text-xl font-bold">Historique des Audits</h2>
            <button
                onClick={onCreate}
                className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600"
            >
                <i className="fas fa-plus mr-2"></i>Nouvel Audit
            </button>
        </div>

        {sessions.length === 0 ? (
            <p className="text-gray-500 text-center py-8">Aucun audit trouvé</p>
        ) : (
            <div className="space-y-2">
                {sessions.map(session => (
                    <div
                        key={session.session_id}
                        className="flex items-center justify-between p-4 border rounded-lg hover:bg-gray-50"
                    >
                        <div className="flex-1 cursor-pointer" onClick={() => onSelect(session)}>
                            <p className="font-medium">{session.name}</p>
                            <p className="text-sm text-gray-500">
                                {new Date(session.created_at).toLocaleString('fr-FR')} -
                                Étape {session.current_step}/6 -
                                <span className={`ml-1 ${session.status === 'completed' ? 'text-green-600' : 'text-blue-600'}`}>
                                    {session.status}
                                </span>
                            </p>
                        </div>
                        <div className="flex gap-2">
                            <button
                                onClick={() => onSelect(session)}
                                className="px-3 py-1 text-blue-500 hover:bg-blue-50 rounded"
                            >
                                <i className="fas fa-arrow-right"></i>
                            </button>
                            <button
                                onClick={() => onDelete(session.session_id)}
                                className="px-3 py-1 text-red-500 hover:bg-red-50 rounded"
                            >
                                <i className="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                ))}
            </div>
        )}
    </div>
);


// ============== Main App ==============

const App = () => {
    const [view, setView] = useState('history'); // history, wizard
    const [sessions, setSessions] = useState([]);
    const [currentSession, setCurrentSession] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    // Step-specific state
    const [items, setItems] = useState([]);
    const [chapters, setChapters] = useState([]);
    const [selectedChapter, setSelectedChapter] = useState('');
    const [results, setResults] = useState([]);
    const [summary, setSummary] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [parsing, setParsing] = useState(false);

    const steps = [
        { title: 'Upload MMEL', description: 'Charger le fichier MMEL PDF' },
        { title: 'Valider MMEL', description: 'Vérifier et corriger le parsing MMEL' },
        { title: 'Upload MEL', description: 'Charger le fichier MEL PDF' },
        { title: 'Valider MEL', description: 'Vérifier et corriger le parsing MEL' },
        { title: 'Audit', description: 'Lancer la comparaison MEL/MMEL' },
        { title: 'Résultats', description: 'Analyser et classifier les écarts' }
    ];

    // Load sessions on mount
    useEffect(() => {
        loadSessions();
    }, []);

    const loadSessions = async () => {
        try {
            const data = await api.getSessions();
            setSessions(data.sessions);
        } catch (err) {
            console.error('Failed to load sessions:', err);
        }
    };

    const createNewSession = async () => {
        try {
            setLoading(true);
            const session = await api.createSession({
                name: `Audit ${new Date().toLocaleString('fr-FR')}`
            });
            setCurrentSession(session);
            setView('wizard');
            await loadSessions();
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const selectSession = async (session) => {
        setCurrentSession(session);
        setView('wizard');

        // Load data based on current step
        if (session.current_step >= 2) {
            await loadItems('MMEL');
        }
        if (session.current_step >= 4) {
            await loadItems('MEL');
        }
        if (session.current_step >= 6) {
            await loadResults();
            await loadSummary();
        }
    };

    const deleteSession = async (sessionId) => {
        if (!confirm('Supprimer cette session?')) return;
        try {
            await api.deleteSession(sessionId);
            await loadSessions();
        } catch (err) {
            setError(err.message);
        }
    };

    const loadItems = async (docType) => {
        try {
            const endpoint = docType === 'MMEL' ? 'step2' : 'step4';
            const params = selectedChapter ? `?chapter=${selectedChapter}` : '';
            const data = await api.request('GET', `/api/sessions/${currentSession.session_id}/${endpoint}/items${params}`);
            setItems(data.items);
            setChapters(data.chapters);
        } catch (err) {
            setError(err.message);
        }
    };

    const loadResults = async () => {
        try {
            const data = await api.getResults(currentSession.session_id);
            setResults(data.results);
        } catch (err) {
            setError(err.message);
        }
    };

    const loadSummary = async () => {
        try {
            const data = await api.getSummary(currentSession.session_id);
            setSummary(data);
        } catch (err) {
            setError(err.message);
        }
    };

    // Step handlers
    const handleUploadMMEL = async (file) => {
        try {
            setUploading(true);
            await api.uploadMMEL(currentSession.session_id, file);
            setParsing(true);
            await api.parseMMEL(currentSession.session_id);
            // Refresh session
            const session = await api.getSession(currentSession.session_id);
            setCurrentSession(session);
            await loadItems('MMEL');
        } catch (err) {
            setError(err.message);
        } finally {
            setUploading(false);
            setParsing(false);
        }
    };

    const handleUploadMEL = async (file) => {
        try {
            setUploading(true);
            await api.uploadMEL(currentSession.session_id, file);
            setParsing(true);
            await api.parseMEL(currentSession.session_id);
            const session = await api.getSession(currentSession.session_id);
            setCurrentSession(session);
            await loadItems('MEL');
        } catch (err) {
            setError(err.message);
        } finally {
            setUploading(false);
            setParsing(false);
        }
    };

    const handleUpdateItem = async (itemId, field, value) => {
        try {
            await api.updateItem(currentSession.session_id, itemId, { [field]: value });
            // Refresh items
            const docType = currentSession.current_step <= 2 ? 'MMEL' : 'MEL';
            await loadItems(docType);
        } catch (err) {
            setError(err.message);
        }
    };

    const handleAddAnnotation = async (itemId, data) => {
        try {
            await api.addAnnotation(currentSession.session_id, itemId, data);
            const docType = currentSession.current_step <= 2 ? 'MMEL' : 'MEL';
            await loadItems(docType);
        } catch (err) {
            setError(err.message);
        }
    };

    const handleDeleteAnnotation = async (annotationId) => {
        try {
            await api.deleteAnnotation(currentSession.session_id, annotationId);
            const docType = currentSession.current_step <= 2 ? 'MMEL' : 'MEL';
            await loadItems(docType);
        } catch (err) {
            setError(err.message);
        }
    };

    const handleValidateStep = async (stepNum) => {
        try {
            setLoading(true);
            if (stepNum === 2) {
                await api.validateMMEL(currentSession.session_id, {});
            } else if (stepNum === 4) {
                await api.validateMEL(currentSession.session_id, {});
            } else if (stepNum === 6) {
                await api.completeAudit(currentSession.session_id, {});
            }
            const session = await api.getSession(currentSession.session_id);
            setCurrentSession(session);
            await loadSessions();
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleRunAudit = async () => {
        try {
            setLoading(true);
            await api.runAudit(currentSession.session_id);
            const session = await api.getSession(currentSession.session_id);
            setCurrentSession(session);
            await loadResults();
            await loadSummary();
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const handleValidateHITL = async (resultId, decision) => {
        try {
            await api.validateHITL(currentSession.session_id, resultId, { decision });
            await loadResults();
            await loadSummary();
        } catch (err) {
            setError(err.message);
        }
    };

    const handleChapterChange = async (chapter) => {
        setSelectedChapter(chapter);
        const docType = currentSession.current_step <= 2 ? 'MMEL' : 'MEL';
        const params = chapter ? `?chapter=${chapter}` : '';
        const endpoint = docType === 'MMEL' ? 'step2' : 'step4';
        try {
            const data = await api.request('GET', `/api/sessions/${currentSession.session_id}/${endpoint}/items${params}`);
            setItems(data.items);
        } catch (err) {
            setError(err.message);
        }
    };

    // Render step content
    const renderStepContent = () => {
        const step = currentSession?.current_step || 1;

        switch (step) {
            case 1:
                return (
                    <div className="space-y-6">
                        <h2 className="text-xl font-bold">Étape 1: Charger le fichier MMEL</h2>
                        <p className="text-gray-600">Téléchargez le fichier MMEL (Master Minimum Equipment List) au format PDF.</p>
                        <FileUpload
                            onUpload={handleUploadMMEL}
                            label="Déposez le fichier MMEL ici"
                            uploading={uploading || parsing}
                        />
                        {parsing && (
                            <div className="text-center text-blue-600">
                                <i className="fas fa-spinner fa-spin mr-2"></i>
                                Analyse du document en cours...
                            </div>
                        )}
                    </div>
                );

            case 2:
                return (
                    <div className="space-y-6">
                        <div className="flex justify-between items-center">
                            <div>
                                <h2 className="text-xl font-bold">Étape 2: Valider le parsing MMEL</h2>
                                <p className="text-gray-600">Vérifiez et corrigez les items extraits du MMEL.</p>
                            </div>
                            <button
                                onClick={() => handleValidateStep(2)}
                                disabled={loading}
                                className="px-6 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 disabled:opacity-50"
                            >
                                <i className="fas fa-check mr-2"></i>
                                Valider et continuer
                            </button>
                        </div>
                        <ItemsTable
                            items={items}
                            chapters={chapters}
                            onUpdateItem={handleUpdateItem}
                            onAddAnnotation={handleAddAnnotation}
                            onDeleteAnnotation={handleDeleteAnnotation}
                            sessionId={currentSession.session_id}
                            selectedChapter={selectedChapter}
                            onChapterChange={handleChapterChange}
                        />
                    </div>
                );

            case 3:
                return (
                    <div className="space-y-6">
                        <h2 className="text-xl font-bold">Étape 3: Charger le fichier MEL</h2>
                        <p className="text-gray-600">Téléchargez le fichier MEL (Minimum Equipment List) au format PDF.</p>
                        <FileUpload
                            onUpload={handleUploadMEL}
                            label="Déposez le fichier MEL ici"
                            uploading={uploading || parsing}
                        />
                        {parsing && (
                            <div className="text-center text-blue-600">
                                <i className="fas fa-spinner fa-spin mr-2"></i>
                                Analyse du document en cours...
                            </div>
                        )}
                    </div>
                );

            case 4:
                return (
                    <div className="space-y-6">
                        <div className="flex justify-between items-center">
                            <div>
                                <h2 className="text-xl font-bold">Étape 4: Valider le parsing MEL</h2>
                                <p className="text-gray-600">Vérifiez et corrigez les items extraits du MEL.</p>
                            </div>
                            <button
                                onClick={() => handleValidateStep(4)}
                                disabled={loading}
                                className="px-6 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 disabled:opacity-50"
                            >
                                <i className="fas fa-check mr-2"></i>
                                Valider et continuer
                            </button>
                        </div>
                        <ItemsTable
                            items={items}
                            chapters={chapters}
                            onUpdateItem={handleUpdateItem}
                            onAddAnnotation={handleAddAnnotation}
                            onDeleteAnnotation={handleDeleteAnnotation}
                            sessionId={currentSession.session_id}
                            selectedChapter={selectedChapter}
                            onChapterChange={handleChapterChange}
                        />
                    </div>
                );

            case 5:
                return (
                    <div className="space-y-6 text-center">
                        <h2 className="text-xl font-bold">Étape 5: Lancer l'audit</h2>
                        <p className="text-gray-600">
                            Comparez le MEL avec le MMEL pour détecter les écarts.
                        </p>
                        <div className="py-8">
                            <button
                                onClick={handleRunAudit}
                                disabled={loading}
                                className="px-8 py-4 bg-blue-500 text-white text-xl rounded-lg hover:bg-blue-600 disabled:opacity-50"
                            >
                                {loading ? (
                                    <><i className="fas fa-spinner fa-spin mr-2"></i>Audit en cours...</>
                                ) : (
                                    <><i className="fas fa-search mr-2"></i>Lancer l'audit</>
                                )}
                            </button>
                        </div>
                    </div>
                );

            case 6:
                return (
                    <div className="space-y-6">
                        <div className="flex justify-between items-center">
                            <div>
                                <h2 className="text-xl font-bold">Étape 6: Résultats de l'audit</h2>
                                <p className="text-gray-600">Analysez et classifiez les écarts détectés.</p>
                            </div>
                            {currentSession.status !== 'completed' && (
                                <button
                                    onClick={() => handleValidateStep(6)}
                                    disabled={loading}
                                    className="px-6 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 disabled:opacity-50"
                                >
                                    <i className="fas fa-check mr-2"></i>
                                    Terminer l'audit
                                </button>
                            )}
                        </div>

                        <SummaryDashboard summary={summary} />

                        <div className="bg-white rounded-lg shadow p-4">
                            <h3 className="font-medium mb-4">Détail des comparaisons</h3>
                            <ResultsTable
                                results={results}
                                onValidateHITL={handleValidateHITL}
                            />
                        </div>
                    </div>
                );

            default:
                return <p>Étape non reconnue</p>;
        }
    };

    return (
        <div className="min-h-screen bg-gray-100">
            {/* Header */}
            <header className="bg-white shadow">
                <div className="max-w-7xl mx-auto px-4 py-4 flex justify-between items-center">
                    <div className="flex items-center">
                        <i className="fas fa-plane text-blue-500 text-2xl mr-3"></i>
                        <h1 className="text-xl font-bold">MoA_MEL Audit</h1>
                    </div>
                    {view === 'wizard' && (
                        <button
                            onClick={() => {
                                setView('history');
                                setCurrentSession(null);
                                loadSessions();
                            }}
                            className="text-gray-600 hover:text-gray-800"
                        >
                            <i className="fas fa-arrow-left mr-2"></i>
                            Retour à l'historique
                        </button>
                    )}
                </div>
            </header>

            {/* Main Content */}
            <main className="max-w-7xl mx-auto px-4 py-8">
                {/* Error Alert */}
                {error && (
                    <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4 flex justify-between">
                        <span>{error}</span>
                        <button onClick={() => setError(null)}><i className="fas fa-times"></i></button>
                    </div>
                )}

                {view === 'history' ? (
                    <SessionHistory
                        sessions={sessions}
                        onSelect={selectSession}
                        onDelete={deleteSession}
                        onCreate={createNewSession}
                    />
                ) : (
                    <div className="bg-white rounded-lg shadow p-6">
                        <StepIndicator currentStep={currentSession?.current_step || 1} steps={steps} />
                        {renderStepContent()}
                    </div>
                )}
            </main>
        </div>
    );
};

// Render
ReactDOM.createRoot(document.getElementById('root')).render(<App />);
