import { Navigate, useParams } from "react-router-dom";

/**
 * Canonical kind-URL aliases — the URLs QR bin labels encode
 * (`/inventory/tool/<id>`, `/inventory/battery/<id>`). They carry
 * no page of their own: each redirects to the concrete detail
 * route, so a scanned label lands exactly where the list's own
 * links land (behind the same auth + module gates).
 */
export function ToolKindRedirect() {
  const { id } = useParams();
  return <Navigate to={`/inventory/${id}`} replace />;
}

export function BatteryKindRedirect() {
  const { id } = useParams();
  return <Navigate to={`/inventory/batteries/${id}`} replace />;
}
