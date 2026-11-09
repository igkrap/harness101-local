import React, { useState, useEffect, useRef } from 'react';
import { SideNav, SideNavSection, SideNavItem } from '@astryxdesign/core/SideNav';
import { TabList, Tab } from '@astryxdesign/core/TabList';
import { VStack } from '@astryxdesign/core/VStack';
import { HStack } from '@astryxdesign/core/HStack';
import { Text } from '@astryxdesign/core/Text';
import { IconButton } from '@astryxdesign/core/IconButton';
import { Icon } from '@astryxdesign/core/Icon';
import workspace from './workspace.json';

type ScreenModule = {
  meta: { title: string };
  default: React.ComponentType;
};

const screenModules = import.meta.glob('./screens/*.tsx', { eager: true }) as Record<string, ScreenModule>;

const screens: Record<string, ScreenModule> = Object.fromEntries(
  Object.entries(screenModules).map(([path, mod]) => [
    path.split('/').pop()?.replace('.tsx', '') || '',
    mod
  ])
);

export default function App() {
  const [activeTab, setActiveTab] = useState(workspace.activeTab);
  const [isCollapsed, setIsCollapsed] = useState(workspace.sidebarCollapsed);
  const [tabs, setTabs] = useState<string[]>(workspace.tabs);
  const lastWorkspaceRef = useRef<string>('');

  useEffect(() => {
    const json = JSON.stringify(workspace);
    if (json !== lastWorkspaceRef.current) {
      lastWorkspaceRef.current = json;
      const validIds = Object.keys(screens);
      const newTabs = workspace.tabs.filter(id => validIds.includes(id));
      setTabs(newTabs);
      setIsCollapsed(workspace.sidebarCollapsed);
      const nextTab = newTabs.includes(workspace.activeTab) ? workspace.activeTab : (newTabs[0] || '');
      setActiveTab(nextTab);
    }
  }, [workspace]);

  const closeTab = (id: string) => {
    const newTabs = tabs.filter(t => t !== id);
    setTabs(newTabs);
    if (activeTab === id) {
      setActiveTab(newTabs.length > 0 ? newTabs[newTabs.length - 1] : '');
    }
  };

  return (
    <HStack style={{ height: '100vh' }}>
              <SideNav 
          collapsible={{ 
            isCollapsed, 
            onCollapsedChange: setIsCollapsed,
            hasButton: true,
            buttonLabel: '토글'
          }}
        >
          <VStack gap={2} style={{ padding: '16px 8px' }}>
            <HStack gap={2} style={{ padding: '0 8px' }}>
              <Icon icon="wrench" />
              {!isCollapsed && <Text style={{ fontWeight: 'bold', letterSpacing: '1px' }}>MANUFACTURING SYSTEM</Text>}
            </HStack>
          </VStack>
          <SideNavSection title="메뉴">
            {Object.entries(screens).map(([id, screen]) => (
              <SideNavItem 
                key={id} 
                label={screen.meta.title} 
                onClick={() => {
                  if (!tabs.includes(id)) setTabs([...tabs, id]);
                  setActiveTab(id);
                }} 
              />
            ))}
          </SideNavSection>
        </SideNav>

      <VStack style={{ flex: 1, overflow: 'auto' }}>
        <TabList value={activeTab} onChange={setActiveTab} hasDivider>
          {tabs.map(id => (
            <HStack key={id} gap={0}>
              <Tab 
                value={id} 
                label={screens[id]?.meta.title || id}
              />
              <IconButton
                label={`${screens[id]?.meta.title || id} 닫기`}
                icon={<Icon icon="close" />}
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  closeTab(id);
                }}
              />
            </HStack>
          ))}
        </TabList>

        <VStack gap={0} style={{ padding: '24px' }}>
          {tabs.length === 0 ? (
            <Text>활성화된 탭이 없습니다.</Text>
          ) : (
            tabs.map(id => {
              const ScreenComponent = screens[id]?.default;
              if (!ScreenComponent) return null;
              return (
                <VStack 
                  key={id} 
                  style={{ display: activeTab === id ? 'flex' : 'none' }}
                >
                  <ScreenComponent />
                </VStack>
              );
            })
          )}
        </VStack>
      </VStack>
    </HStack>
  );
}
