import { useEffect, useState } from 'react';
import { currentBranding, subscribeBranding, type Branding } from './branding';

export function useBranding(): Branding {
  const [branding, setBranding] = useState(currentBranding());
  useEffect(() => subscribeBranding(setBranding), []);
  return branding;
}
