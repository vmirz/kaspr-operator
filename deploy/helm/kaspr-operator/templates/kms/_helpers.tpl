{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "kaspr.kms.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "kaspr.kms.labels" -}}
helm.sh/chart: {{ include "kaspr.kms.chart" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}


{{/*
Allow the release namespace to be overridden for multi-namespace deployments in combined charts
*/}}
{{- define "kaspr.kms.namespace" -}}
{{- .Release.Namespace -}}
{{- end -}}
