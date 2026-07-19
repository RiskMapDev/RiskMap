export interface District {
  id: number; name: string; name_kz: string; code: string;
  population: number; area_km2: number; center: string;
  lat: number | null; lng: number | null; boundary_geojson: any;
  locality_count: number; officials: Official[]; localities: Locality[];
}
export interface Official { id: number; full_name: string; position: string; position_name: string; phone: string; }
export interface Locality { id: number; name: string; population: number; is_center: boolean; }
export interface BudgetProgram {
  id: number; district: number; year: number; sphere: string; sphere_display: string;
  program_name: string; allocated: number; spent: number; remainder: number; execution_pct: number;
}
export interface ProcurementContract {
  id: number; district: number; contract_number: string; customer_name: string;
  supplier_name: string; supplier_bin: string; subject: string; method_display: string;
  amount: number; status_display: string; year: number;
  risk_single: boolean; risk_overpriced: boolean; risk_splitting: boolean;
  risk_affiliation: boolean; risk_count: number;
}
export interface ConstructionObject {
  id: number; name: string; category_display: string; district: number;
  customer_name: string; contractor_name: string; design_cost: number;
  contract_amount: number; readiness_pct: number; risk_level: string;
  risk_level_display: string; lat: number | null; lng: number | null;
}
export interface RiskMaterial {
  id: number; district: number; district_name: string; sphere_display: string;
  subject_name: string; amount: number; description: string;
  status: string; status_display: string; level: string; level_display: string;
  analyst_name: string; detected_at: string; year: number;
}
export interface DashboardData {
  year: number; district_count: number;
  budget: { total: number; spent: number; by_sphere: { sphere: string; allocated: number; spent: number }[] };
  risks: { total_amount: number; count: number; by_sphere: any[]; by_status: any[]; erdr_count: number; prevention_count: number; completed_count: number };
  procurement: { total: number; count: number };
  top_districts: { district__id: number; district__name: string; total_risk: number }[];
  top_suppliers: { supplier_name: string; supplier_bin: string; total: number }[];
  top_subsidy_recipients: { name: string; bin_iin: string; total: number }[];
}
export interface User { id: number; username: string; email: string; first_name: string; last_name: string; role: string; department: string; }
