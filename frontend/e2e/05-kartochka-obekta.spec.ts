import { expect, test, type APIRequestContext } from "@playwright/test";

import { apiContext, auth, fetchObjects, loginApi, url } from "./helpers/api";

/**
 * Сценарий 5 приёмки: карточка объекта с расшифровкой риска, включая раздел
 * «не измерено».
 *
 * Почему раздел «не измерено» обязателен. Балл риска складывается из
 * индикаторов, и часть из них по конкретному объекту посчитать не из чего:
 * поля нет в источнике. Если карточка покажет только сработавшие индикаторы,
 * низкий балл прочитается как «проверено и благополучно», хотя верное чтение —
 * «проверено наполовину». Разница определяет, поедет ли проверка на объект.
 * Ровно поэтому ТЗ 14 требует расшифровку, а критерий приёмки 23.7 говорит
 * «рассчитываются И расшифровываются».
 *
 * Экрана карточки в интерфейсе нет (см. `test.fixme` в конце файла), поэтому
 * проверяется API карточки — тот самый, который экран будет показывать.
 */

let api: APIRequestContext;

test.beforeAll(async () => {
  api = await apiContext();
});

test.afterAll(async () => {
  await api.dispose();
});

interface FactorRow {
  code: string;
  measured: boolean;
  effect: string;
  note: string;
}

interface ObjectCard {
  object_type: string;
  object_id: string;
  title: string;
  source_layer: string;
  territory: { code: string | null; name: string | null };
  risk: {
    score: number | null;
    level: string;
    is_preliminary: boolean;
    completeness: number | null;
    model_code: string | null;
    model_version: string | null;
    explanation: string;
    notes: string[];
  };
  factors: { measured: FactorRow[]; unmeasured: FactorRow[] };
}

async function openCard(
  token: string,
  objectType: string,
  objectId: string,
): Promise<ObjectCard> {
  const response = await api.get(url(`/objects/${objectType}/${objectId}`), {
    headers: auth(token),
  });
  expect(response.status(), `карточка ${objectType}/${objectId} не открылась`).toBe(200);
  return (await response.json()) as ObjectCard;
}

test.describe("Сценарий 5. Карточка объекта и расшифровка риска", () => {
  test("карточка объекта с полной оценкой объясняет, из чего сложился балл", async () => {
    const token = await loginApi(api, "analyst");

    // Берём объект с наибольшим риском — у него оценка заведомо посчитана.
    const page = await fetchObjects(api, token, {
      page_size: 1,
      sort: "risk",
      order: "desc",
    });
    const target = page.items[0];
    expect(target, "выборка пуста, брать нечего").toBeTruthy();

    const card = await openCard(token, target.object_type, target.object_id);

    expect(card.title.length, "у карточки нет заголовка").toBeGreaterThan(0);
    expect(card.risk.level, "уровень в карточке и в списке разошёлся").toBe(target.risk_level);
    expect(card.risk.score, "балл не посчитан").not.toBeNull();

    /*
      Модель и её версия обязательны: балл без указания, по какой методике он
      получен, невозможно ни оспорить, ни воспроизвести — а решения по нему
      принимаются административные.
    */
    expect(card.risk.model_code, "не указана модель риска").toBeTruthy();
    expect(card.risk.model_version, "не указана версия модели").toBeTruthy();

    // Расшифровка — не пустой список: хотя бы один индикатор с вкладом.
    expect(card.factors.measured.length, "нет ни одного измеренного индикатора").toBeGreaterThan(
      0,
    );
    for (const factor of card.factors.measured) {
      expect(factor.measured, "индикатор в разделе измеренных помечен как неизмеренный").toBe(
        true,
      );
      expect(factor.effect, `индикатор ${factor.code} без описания влияния`).not.toBe("");
    }
  });

  test("карточка объекта с неполными данными показывает раздел «не измерено»", async () => {
    const token = await loginApi(api, "analyst");

    /*
      Уровень «нет данных» назначается именно тогда, когда измерено слишком
      мало индикаторов, — такой объект и нужен, чтобы проверить раздел.
    */
    const page = await fetchObjects(api, token, { page_size: 5, risk_levels: "unknown" });
    test.skip(
      page.items.length === 0,
      "на стенде нет объектов без измеренного уровня — проверять раздел не на чем",
    );

    const target = page.items[0];
    const card = await openCard(token, target.object_type, target.object_id);

    expect(card.risk.level, "ожидался объект без измеренного уровня").toBe("unknown");

    // Полнота меньше единицы — иначе «нет данных» было бы необъяснимо.
    expect(card.risk.completeness ?? 1).toBeLessThan(1);

    // Балл помечен предварительным: показывать его наравне с посчитанным по
    // полным данным значит уравнять измеренное и недоизмеренное.
    expect(card.risk.is_preliminary, "неполная оценка не помечена предварительной").toBe(true);

    // Собственно раздел «не измерено».
    expect(
      card.factors.unmeasured.length,
      "у объекта с неполной оценкой пуст раздел «не измерено» — низкая полнота ничем не объяснена",
    ).toBeGreaterThan(0);

    for (const factor of card.factors.unmeasured) {
      expect(factor.measured, "индикатор в разделе «не измерено» помечен измеренным").toBe(false);
      expect(factor.effect, `индикатор ${factor.code} не подписан как неизмеренный`).toBe(
        "не измерено",
      );
      // Причина обязательна: «не измерено» без причины неотличимо от
      // «забыли посчитать».
      expect(factor.note, `индикатор ${factor.code} без причины отсутствия`).not.toBe("");
    }

    /*
      Текстовое объяснение обязано называть число неизмеренных индикаторов:
      именно оно переводит «полнота 45 %» в понятное «четыре показателя не из
      чего было посчитать».
    */
    expect(card.risk.explanation, "нет текстового объяснения оценки").toContain("Не измерено");
  });

  test("карточка называет территорию и слой-источник", async () => {
    /*
      Без источника карточка не проверяема: пользователь не может пойти в
      исходную книгу и сверить значение, а значит, вынужден верить на слово.
    */
    const token = await loginApi(api, "analyst");
    const page = await fetchObjects(api, token, { page_size: 1, object_types: "contract" });
    const target = page.items[0];
    const card = await openCard(token, target.object_type, target.object_id);

    expect(card.source_layer, "не указан слой-источник").toMatch(/^8\.\d$/);
    expect(card.territory.name, "не указана территория объекта").toBeTruthy();
  });

  test.fixme(
    "карточка объекта открывается из интерфейса кликом по объекту выборки",
    async () => {
      /*
        НЕ РЕАЛИЗОВАНО В ПРИЛОЖЕНИИ.

        Маршрута карточки объекта во фронтенде нет: в `src/app/` есть только
        login, dashboard, map, import, reports, graph, admin. Компонент
        `ResultCard` умеет отрисовать объект выборки, но ни он, ни `ResultList`
        никуда не подключены, а `TerritoryPopup` содержит кнопку «Открыть
        карточку» без обработчика — `MapScreen` не передаёт `onOpenCard`.

        Открыть карточку через интерфейс невозможно, поэтому UI-теста нет.
        Данные, которые карточка обязана показать, проверены выше через
        `GET /api/v1/objects/{type}/{id}` — тот же источник, из которого экран
        и будет их брать.
      */
    },
  );
});
