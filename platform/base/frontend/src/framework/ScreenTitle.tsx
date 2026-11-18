import type { ReactNode } from 'react';
import { Heading } from './ui';

export type ScreenTitleProps = { children: ReactNode; level?: 1 | 2 | 3 };

export function ScreenTitle({ children, level = 2 }: ScreenTitleProps) {
  return <Heading level={level} style={{ fontSize: level === 3 ? 13 : 15, lineHeight: level === 3 ? '18px' : '24px', fontWeight: 600, margin: 0 }}>{children}</Heading>;
}
