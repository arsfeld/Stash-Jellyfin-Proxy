import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { 
  Activity, 
  Server, 
  Users, 
  Database, 
  ArrowUpRight, 
  RefreshCw,
  Play,
  Pause,
  FileText
} from "lucide-react";

export default function Dashboard() {
  return (
    <div className="p-6 md:p-8 space-y-8 max-w-7xl mx-auto animate-in fade-in duration-500">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight font-mono">SYSTEM STATUS</h2>
          <p className="text-muted-foreground font-mono text-sm mt-1">Active Session ID: 8f7d-2a1b</p>
        </div>
        <div className="flex gap-2">
            <Button variant="outline" size="sm" className="font-mono border-primary/20 text-primary hover:bg-primary/10">
              <RefreshCw className="w-4 h-4 mr-2" />
              RELOAD
            </Button>
            <Button size="sm" className="font-mono bg-primary text-primary-foreground hover:bg-primary/90">
              <Play className="w-4 h-4 mr-2" />
              START PROXY
            </Button>
        </div>
      </div>

      {/* Status Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="bg-card border-border/50">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium font-mono text-muted-foreground">
              STASH CONNECTION
            </CardTitle>
            <Server className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-foreground">CONNECTED</div>
            <p className="text-xs text-muted-foreground mt-1 font-mono">
              stash.feldorn.com:443
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border/50">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium font-mono text-muted-foreground">
              ACTIVE CLIENTS
            </CardTitle>
            <Users className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-foreground">1</div>
            <p className="text-xs text-muted-foreground mt-1 font-mono">
              Infuse (iOS) - 192.168.1.45
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border/50">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium font-mono text-muted-foreground">
              LIBRARY ITEMS
            </CardTitle>
            <Database className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-foreground">12,450</div>
            <p className="text-xs text-muted-foreground mt-1 font-mono">
              Mapped from Stash GraphQL
            </p>
          </CardContent>
        </Card>

        <Card className="bg-card border-border/50">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium font-mono text-muted-foreground">
              UPTIME
            </CardTitle>
            <Activity className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-foreground">99.9%</div>
            <p className="text-xs text-muted-foreground mt-1 font-mono">
              Last restart: 2d ago
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Main Log/Activity Area */}
      <div className="grid gap-4 md:grid-cols-7">
        <Card className="col-span-4 bg-card border-border/50">
          <CardHeader>
            <CardTitle className="font-mono text-sm text-muted-foreground uppercase">Live Logs</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="bg-black/40 rounded-md p-4 h-[300px] overflow-y-auto font-mono text-xs space-y-1 border border-border/30">
              <div className="text-muted-foreground"><span className="text-primary">[10:42:01]</span> INFO: Starting Stash-Jellyfin Proxy on 0.0.0.0:8096</div>
              <div className="text-muted-foreground"><span className="text-primary">[10:42:01]</span> INFO: Target Stash: https://stash.feldorn.com</div>
              <div className="text-muted-foreground"><span className="text-primary">[10:42:05]</span> INFO: Connection established with Stash GraphQL</div>
              <div className="text-foreground"><span className="text-blue-400">[10:45:22]</span> REQ: POST /Users/AuthenticateByName from 192.168.1.45</div>
              <div className="text-foreground"><span className="text-blue-400">[10:45:22]</span> RES: 200 OK (Auth Successful)</div>
              <div className="text-foreground"><span className="text-blue-400">[10:45:23]</span> REQ: GET /Users/user-1/Views</div>
              <div className="text-foreground"><span className="text-blue-400">[10:45:25]</span> REQ: GET /Users/user-1/Items?ParentId=root-scenes</div>
              <div className="text-yellow-500"><span className="text-yellow-500">[10:45:25]</span> WARN: Slow query on Stash (450ms)</div>
            </div>
          </CardContent>
        </Card>

        <Card className="col-span-3 bg-card border-border/50">
          <CardHeader>
            <CardTitle className="font-mono text-sm text-muted-foreground uppercase">Quick Actions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
               <h4 className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Service Control</h4>
               <div className="flex gap-2">
                 <Button variant="outline" className="w-full justify-start font-mono text-xs">
                    <Pause className="w-3 h-3 mr-2" /> STOP SERVICE
                 </Button>
                 <Button variant="outline" className="w-full justify-start font-mono text-xs">
                    <RefreshCw className="w-3 h-3 mr-2" /> RESTART
                 </Button>
               </div>
            </div>

            <div className="space-y-2 pt-4 border-t border-border/30">
               <h4 className="text-xs font-mono text-muted-foreground uppercase tracking-wider">Debug</h4>
               <Button variant="secondary" className="w-full justify-start font-mono text-xs">
                  <FileText className="w-3 h-3 mr-2" /> VIEW RAW LOGS
               </Button>
               <Button variant="secondary" className="w-full justify-start font-mono text-xs">
                  <Database className="w-3 h-3 mr-2" /> FORCE SYNC METADATA
               </Button>
            </div>

            <div className="pt-4 border-t border-border/30">
              <div className="bg-primary/10 p-3 rounded border border-primary/20">
                <h4 className="text-primary text-xs font-bold font-mono mb-1">VERSION 1.0 AVAILABLE</h4>
                <p className="text-xs text-muted-foreground">
                  The python script has been generated and is ready for download.
                </p>
                <Button size="sm" className="w-full mt-3 font-mono text-xs bg-primary text-primary-foreground">
                  DOWNLOAD SCRIPT
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
