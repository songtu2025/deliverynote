export interface OverreceiptRuleVersion {
  id: number;
  name: string;
  short_tail_limit: number;
  medium_tail_limit: number;
  long_tail_limit: number;
  allowed_warehouses: string[];
  active: boolean;
  created_by: number;
  created_at: string;
}

export interface SelfOperatedOverreceiptRuleVersion {
  id: number;
  name: string;
  allowance: number;
  active: boolean;
  created_by: number;
  created_at: string;
}
