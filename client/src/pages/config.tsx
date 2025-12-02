import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { Save, Download } from "lucide-react";

export default function Config() {
  return (
    <div className="p-6 md:p-8 space-y-8 max-w-4xl mx-auto animate-in slide-in-from-bottom-4 duration-500">
      <div>
        <h2 className="text-2xl font-bold tracking-tight font-mono">CONFIGURATION</h2>
        <p className="text-muted-foreground font-mono text-sm mt-1">Manage settings for stash-jellyfin-proxy</p>
      </div>

      <Card className="bg-card border-border/50">
        <CardHeader>
          <CardTitle className="font-mono text-base">Stash Connection</CardTitle>
          <CardDescription className="font-mono text-xs">Where is your Stash instance located?</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2">
            <Label htmlFor="stash-url" className="font-mono text-xs uppercase">Stash URL</Label>
            <Input id="stash-url" defaultValue="https://stash.feldorn.com" className="font-mono bg-background/50" />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="api-key" className="font-mono text-xs uppercase">API Key</Label>
            <Input id="api-key" type="password" value="eyJhbGciOiJIUz..." className="font-mono bg-background/50" readOnly />
            <p className="text-[10px] text-muted-foreground">Loaded from .scripts.conf</p>
          </div>
        </CardContent>
      </Card>

      <Card className="bg-card border-border/50">
        <CardHeader>
          <CardTitle className="font-mono text-base">Proxy Settings</CardTitle>
          <CardDescription className="font-mono text-xs">Network and Auth settings for the proxy</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label htmlFor="bind-addr" className="font-mono text-xs uppercase">Bind Address</Label>
              <Input id="bind-addr" defaultValue="0.0.0.0" className="font-mono bg-background/50" />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="port" className="font-mono text-xs uppercase">Port</Label>
              <Input id="port" defaultValue="8096" className="font-mono bg-background/50" />
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="proxy-key" className="font-mono text-xs uppercase">Proxy Auth Key (Infuse Password)</Label>
            <Input id="proxy-key" defaultValue="infuse12345" className="font-mono bg-background/50" />
          </div>
        </CardContent>
      </Card>

      <Card className="bg-card border-border/50">
        <CardHeader>
          <CardTitle className="font-mono text-base">Generated Config File</CardTitle>
          <CardDescription className="font-mono text-xs">Preview of .scripts.conf</CardDescription>
        </CardHeader>
        <CardContent>
          <Textarea 
            className="font-mono text-xs bg-black/40 border-border/30 min-h-[200px]" 
            readOnly 
            value={`STASH_URL = "https://stash.feldorn.com"
STASH_API_KEY = "eyJhbGciOiJIUz..."
MEDIA_ROOTS = ["/data/Video-A", "/data/Video-B", "/data2/Video-B"]
PROXY_BIND = "0.0.0.0"
PROXY_PORT = 8096
PROXY_API_KEY = "infuse12345"`}
          />
        </CardContent>
      </Card>

      <div className="flex justify-end gap-4">
        <Button variant="outline" className="font-mono">
          <Download className="w-4 h-4 mr-2" /> EXPORT CONFIG
        </Button>
        <Button className="font-mono bg-primary text-primary-foreground hover:bg-primary/90">
          <Save className="w-4 h-4 mr-2" /> SAVE CHANGES
        </Button>
      </div>
    </div>
  );
}
