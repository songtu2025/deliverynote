export type Role = "admin" | "operator";

export interface User {
  id: number;
  username: string;
  role: Role;
  active: boolean;
}

export interface AuditLog {
  id: number;
  user_id: number | null;
  action: string;
  entity_type: string;
  entity_id: string;
  details: Record<string, unknown>;
  created_at: string;
}
