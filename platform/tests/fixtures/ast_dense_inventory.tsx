import { Button } from '@astryxdesign/core/Button';
import { Card } from '@astryxdesign/core/Card';
import { Heading } from '@astryxdesign/core/Heading';
import { HStack } from '@astryxdesign/core/HStack';
import { Spinner } from '@astryxdesign/core/Spinner';
import { pixel,proportional,Table,TableColumn } from '@astryxdesign/core/Table';
import { Text } from '@astryxdesign/core/Text';
import { TextInput } from '@astryxdesign/core/TextInput';
import { VStack } from '@astryxdesign/core/VStack';
import { useEffect,useState } from 'react';


// Types
export interface InventoryItem extends Record<string, unknown> {
  id: number;
  name: string;
  category: string;
  quantity: number;
  minQuantity: number;
  unitPrice: number;
  createdAt: string;
}

export const meta = { title: '재고' };

export default function Inventory() {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: '', category: '', quantity: 0, minQuantity: 0, unitPrice: 0 });
  const [isAdding, setIsAdding] = useState(false);

  const fetchInventory = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/inventory');
      if (!res.ok) throw new Error('데이터를 불러오지 못했습니다.');
      const data = await res.json();
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : '알 수 없는 오류');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchInventory(); }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.quantity < 0 || form.minQuantity < 0 || form.unitPrice < 0) return;
    setIsAdding(true);
    try {
      const res = await fetch('/api/inventory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) throw new Error('저장에 실패했습니다.');
      setForm({ name: '', category: '', quantity: 0, minQuantity: 0, unitPrice: 0 });
      await fetchInventory();
    } catch (e) {
      setError(e instanceof Error ? e.message : '오류 발생');
    } finally {
      setIsAdding(false);
    }
  };

  const columns: TableColumn<InventoryItem>[] = [
    { key: 'name', header: '이름', width: proportional(1) },
    { key: 'category', header: '카테고리', width: proportional(1) },
    { key: 'quantity', header: '수량', width: pixel(100), renderCell: (item: InventoryItem) => (
      <Text>{String(item.quantity)} {item.quantity < item.minQuantity ? '(부족)' : ''}</Text>
    )},
    { key: 'minQuantity', header: '최소 수량', width: pixel(100) },
    { key: 'unitPrice', header: '단가', width: pixel(120) },
  ];

  return (
    <HStack gap={4} style={{ height: '100%', width: '100%' }}>
  <VStack gap={4} style={{ flex: 3, minWidth: 0, height: '100%' }} data-testid="main-content-area">
    <Heading level={2}>재고 관리</Heading>
    
    <Card data-testid="query-panel" style={{ flexShrink: 0 }}>
      <form onSubmit={handleSubmit}>
        <VStack gap={2}>
          <HStack gap={2}>
            <TextInput label="이름" value={form.name} onChange={(v) => setForm({...form, name: v})} isRequired />
            <TextInput label="카테고리" value={form.category} onChange={(v) => setForm({...form, category: v})} isRequired />
            <Button onClick={fetchInventory} label="조회" />
          </HStack>
          <HStack gap={2}>
            <TextInput label="수량" value={form.quantity.toString()} onChange={(v) => setForm({...form, quantity: Math.max(0, Number(v))})} isRequired />
            <TextInput label="최소 수량" value={form.minQuantity.toString()} onChange={(v) => setForm({...form, minQuantity: Math.max(0, Number(v))})} isRequired />
            <TextInput label="단가" value={form.unitPrice.toString()} onChange={(v) => setForm({...form, unitPrice: Math.max(0, Number(v))})} isRequired />
            <Button type="submit" label="추가" isLoading={isAdding} />
          </HStack>
        </VStack>
      </form>
    </Card>

    <div data-testid="results-grid" style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
      {loading ? <Spinner /> : error ? (
        <VStack gap={2}>
          <Text>{error}</Text>
          <Button onClick={fetchInventory} label="재시도" />
        </VStack>
      ) : items.length === 0 ? (
        <Text>데이터가 없습니다.</Text>
      ) : (
        <Table data={items} columns={columns} idKey="id" />
      )}
    </div>
  </VStack>

  <VStack gap={4} style={{ flex: 1, minWidth: 250 }} data-testid="side-panel">
    <Card>
      <Heading level={3}>상세 정보</Heading>
      <Text>선택된 항목의 상세 정보가 여기에 표시됩니다.</Text>
    </Card>
  </VStack>
</HStack>
  );
}
