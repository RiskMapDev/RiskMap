import { redirect } from "next/navigation";

/** Корень ведёт на дашборд — он же «Главная» в хлебных крошках по ТЗ. */
export default function RootPage() {
  redirect("/dashboard");
}
