"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useApolloClient, useMutation } from "@apollo/client/react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LOGIN, REGISTER, requestError, type UserError } from "@/lib/gql";

type AuthResult = { user: { id: string } | null; userErrors: UserError[] };

export default function LoginPage() {
  const router = useRouter();
  const client = useApolloClient();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<UserError[]>([]);
  const [login, { loading: l1 }] = useMutation<{ login: AuthResult }>(LOGIN);
  const [register, { loading: l2 }] = useMutation<{ register: AuthResult }>(REGISTER);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrors([]);
    try {
      const vars = { variables: { email, password } };
      const res = mode === "login" ? (await login(vars)).data?.login : (await register(vars)).data?.register;
      if (res?.user) {
        await client.resetStore(); // new session cookie: refetch everything as the new user
        router.push("/");
      } else setErrors(res?.userErrors ?? []);
    } catch (err) {
      setErrors([{ code: "ERROR", message: requestError(err) }]);
    }
  }

  const fieldError = (f: string) => errors.find((e) => e.field === f)?.message;

  return (
    <Card className="mx-auto w-full max-w-md">
      <CardHeader>
        <CardTitle>{mode === "login" ? "Ingresar" : "Crear cuenta"}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="email">Correo</Label>
            <Input id="email" type="email" autoComplete="email" required value={email}
              aria-invalid={!!fieldError("email")} onChange={(e) => setEmail(e.target.value)} />
            {fieldError("email") && <p className="text-xs text-destructive">{fieldError("email")}</p>}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="password">Contraseña</Label>
            <Input id="password" type="password" required minLength={10} maxLength={128}
              autoComplete={mode === "login" ? "current-password" : "new-password"} value={password}
              aria-invalid={!!fieldError("password")} onChange={(e) => setPassword(e.target.value)} />
            {mode === "register" && <p className="text-xs text-muted-foreground">Mínimo 10 caracteres.</p>}
            {fieldError("password") && <p className="text-xs text-destructive">{fieldError("password")}</p>}
          </div>
          {errors.filter((e) => !e.field).map((e) => (
            <p key={e.code} role="alert" className="text-sm text-destructive">{e.message}</p>
          ))}
          <Button type="submit" disabled={l1 || l2}>
            {(l1 || l2) && <Loader2 className="animate-spin" />}
            {mode === "login" ? "Ingresar" : "Crear cuenta"}
          </Button>
          <button type="button" className="text-sm text-primary underline-offset-4 hover:underline"
            onClick={() => { setMode(mode === "login" ? "register" : "login"); setErrors([]); }}>
            {mode === "login" ? "¿No tienes cuenta? Regístrate" : "¿Ya tienes cuenta? Ingresa"}
          </button>
        </form>
      </CardContent>
    </Card>
  );
}
