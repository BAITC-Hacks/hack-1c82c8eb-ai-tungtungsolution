import { useState } from "react";
import { Check, ChevronsUpDown, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { useEmployees } from "./queries";
import { ErrorNotice } from "./shared";
import type { CareerData, Session } from "./types";

export function SessionSwitcher({
  data,
  session,
  onChange,
  disabled,
}: {
  data: CareerData;
  session: Session;
  onChange: (session: Session) => void;
  disabled: boolean;
}) {
  const employees = useEmployees(data);
  const [open, setOpen] = useState(false);
  const current =
    session?.role === "employee"
      ? employees.data?.find((p) => p.id === session.employeeId)
      : null;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label="Выбрать сотрудника"
          className="h-10 max-w-full gap-2 bg-white px-3"
          disabled={disabled}
        >
          <UserRound className="size-4 text-primary" />
          <span className="max-w-36 truncate">
            {current?.name ?? "Выбрать сотрудника"}
          </span>
          <ChevronsUpDown className="size-3 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 max-w-[calc(100vw-2rem)] p-0">
        <Command>
          <CommandInput
            placeholder="Найти по имени или роли…"
            aria-label="Поиск сотрудников"
          />
          <CommandList>
            <CommandEmpty>
              {employees.isPending ? "Загрузка…" : "Сотрудник не найден"}
            </CommandEmpty>
            <ErrorNotice error={employees.error} />
            <CommandGroup heading="Сотрудники">
              {employees.data?.map((employee) => (
                <CommandItem
                  key={employee.id}
                  value={`${employee.name} ${employee.role} ${employee.grade}`}
                  onSelect={() => {
                    onChange({ role: "employee", employeeId: employee.id });
                    setOpen(false);
                  }}
                  className="py-3"
                >
                  <div className="mr-auto">
                    <p>{employee.name}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {employee.role} · {employee.grade}
                    </p>
                  </div>
                  {current?.id === employee.id && (
                    <Check className="size-4 text-primary" />
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
