/**
 * Карточка объекта: запрос и типы ответа.
 *
 * Поля оставлены в том виде, в каком их отдаёт сервер (snake_case), а не
 * переведены в camelCase, как в списке. Причина в `fields` и `provenance`: это
 * словари с произвольными ключами на русском, и «привести к camelCase» их
 * нельзя в принципе. Переименовывать половину структуры, оставив вторую как
 * есть, значило бы завести правило, у которого больше исключений, чем случаев.
 */

import { readToken } from "@/lib/api/auth";
import { request } from "@/lib/api/request";
import type { ObjectType } from "@/lib/query-spec";
import type { RiskLevel } from "@/lib/risk";

/** Один фактор в расшифровке оценки. */
export interface FactorRow {
  code: string;
  name: string;
  /** Вес фактора в модели. `null` — вес не задан, это не ноль. */
  weight: number | null;
  /** Измеренное значение 0..1. `null` у неизмеренных факторов. */
  value: number | null;
  /** Вклад в балл. `null` у неизмеренных: не измерено — значит не вычислено. */
  contribution: number | null;
  measured: boolean;
  /** Как повлиял — словами: «повысил риск», «не повлиял», «не измерено». */
  effect: string;
  /** Причина, почему фактор не измерен, либо примечание к измерению. */
  note: string;
  /** Источник, из которого фактор берётся или должен браться. */
  source: string;
}

export interface ObjectDetailResponse {
  object_type: ObjectType;
  object_id: string;
  title: string;
  source_layer: string;

  territory: {
    code: string | null;
    name: string | null;
    /** Почему территории нет, если её нет. Пустая строка — территория есть. */
    note: string;
  };

  risk: {
    score: number | null;
    level: RiskLevel;
    /** Балл посчитан на неполных данных — показывать наравне с обычным нельзя. */
    is_preliminary: boolean;
    completeness: number | null;
    model_code: string | null;
    model_version: string | null;
    override_reason: string;
    explanation: string;
    notes: string[];
  };

  factors: {
    measured: FactorRow[];
    /** Обязательный раздел: именно он объясняет низкую полноту и серый уровень. */
    unmeasured: FactorRow[];
  };

  /** Сведения объекта: произвольные пары «название поля → значение». */
  fields: Record<string, unknown>;
  /** Происхождение записи: слой, строка источника, даты загрузки и актуальности. */
  provenance: Record<string, unknown>;
}

export function fetchObjectDetail(
  objectType: string,
  objectId: string,
  signal?: AbortSignal,
): Promise<ObjectDetailResponse> {
  return request<ObjectDetailResponse>(
    `/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}`,
    { token: readToken(), signal },
  );
}
