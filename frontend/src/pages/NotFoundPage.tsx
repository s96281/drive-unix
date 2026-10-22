import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Compass, Home } from 'lucide-react';

export function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center px-4">
      <div className="p-4 rounded-full bg-accent/40 mb-4 text-muted-foreground">
        <Compass className="h-12 w-12" />
      </div>
      <h1 className="text-3xl font-bold tracking-tight text-foreground">404 - 找不到此頁面</h1>
      <p className="text-sm text-muted-foreground mt-2 max-w-sm">
        您欲瀏覽的路徑不存在或已被遷移。請點擊下方按鈕返回總覽儀表板。
      </p>
      <Button onClick={() => navigate('/')} className="mt-6 gap-2">
        <Home className="h-4 w-4" /> 返回總覽儀表板
      </Button>
    </div>
  );
}
