import { ModeToggle } from "@/components/mode-toggle";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { setRequestLocale } from "next-intl/server";

export const metadata = {
  title: "Design system showcase",
};

const buttonVariants = [
  "default",
  "secondary",
  "outline",
  "ghost",
  "destructive",
  "link",
] as const;

// Internal kitchen-sink page. Its copy is intentionally left as English demo
// content (not translated) since it only exercises the design-system
// primitives and is not user-facing product UI.
export default async function ShowcasePage({
  params,
}: PageProps<"/[locale]/showcase">) {
  const { locale } = await params;
  setRequestLocale(locale);
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-10 px-6 py-12">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-3xl font-semibold tracking-tight">
            Design system
          </h1>
          <p className="text-muted-foreground">
            Kitchen-sink of the shadcn/ui primitives and theme tokens.
          </p>
        </div>
        <ModeToggle />
      </header>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-medium">Buttons</h2>
        <div className="flex flex-wrap items-center gap-3">
          {buttonVariants.map((variant) => (
            <Button key={variant} variant={variant}>
              {variant}
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm">Small</Button>
          <Button size="default">Default</Button>
          <Button size="lg">Large</Button>
          <Button disabled>Disabled</Button>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-medium">Form controls</h2>
        <div className="flex max-w-sm flex-col gap-2">
          <Label htmlFor="showcase-email">Email</Label>
          <Input
            id="showcase-email"
            type="email"
            placeholder="you@example.com"
          />
          <Label htmlFor="showcase-disabled">Disabled input</Label>
          <Input id="showcase-disabled" placeholder="Unavailable" disabled />
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-medium">Card</h2>
        <Card className="max-w-sm">
          <CardHeader>
            <CardTitle>Your backlog</CardTitle>
            <CardDescription>
              Everything you want to watch, read and play.
            </CardDescription>
            <CardAction>
              <Button variant="ghost" size="sm">
                Edit
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Cards group related content and surface tokenized colors for
              surfaces, borders and text.
            </p>
          </CardContent>
          <CardFooter>
            <Button size="sm">View all</Button>
          </CardFooter>
        </Card>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-medium">Dialog</h2>
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline">Open dialog</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add to library</DialogTitle>
              <DialogDescription>
                Confirm you want to add this title to your backlog.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-2">
              <Label htmlFor="dialog-note">Note</Label>
              <Input id="dialog-note" placeholder="Optional note" />
            </div>
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="ghost">Cancel</Button>
              </DialogClose>
              <DialogClose asChild>
                <Button>Confirm</Button>
              </DialogClose>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </section>
    </main>
  );
}
