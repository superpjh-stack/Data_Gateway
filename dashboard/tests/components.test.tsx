import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { Topology } from '../src/components/Topology'
import { AssumedBadge, DataTable, StatusBadge } from '../src/components/ui'
import type { Topology as Topo } from '../src/lib/types'

describe('StatusBadge', () => {
  it('색만이 아니라 아이콘과 글자를 함께 보여준다', () => {
    render(<StatusBadge status="DOWN" />)
    expect(screen.getByText('끊김')).toBeInTheDocument()
    expect(screen.getByText('✕')).toBeInTheDocument()
  })
})

describe('AssumedBadge', () => {
  it('가정 항목이 있을 때만 보인다', () => {
    const { container, rerender } = render(<AssumedBadge items={[]} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<AssumedBadge items={['레지스터']} />)
    expect(screen.getByText('가정')).toHaveAttribute('title', '현장 확인 필요: 레지스터')
  })
})

describe('DataTable', () => {
  it('머리글을 누르면 정렬 방향이 바뀐다', () => {
    const rows = [{ k: 'b', n: 2 }, { k: 'a', n: 1 }, { k: 'c', n: 3 }]
    render(<DataTable rows={rows} rowKey={(r) => r.k} columns={[{ key: 'n', label: '번호', render: (r) => r.n, sort: (r) => r.n }]} />)
    const cells = () => screen.getAllByRole('cell').map((c) => c.textContent)
    expect(cells()).toEqual(['2', '1', '3'])
    fireEvent.click(screen.getByText('번호'))
    expect(cells()).toEqual(['1', '2', '3'])
    fireEvent.click(screen.getByText(/번호/))
    expect(cells()).toEqual(['3', '2', '1'])
  })
})

describe('Topology', () => {
  it('장애 링크와 노드를 상태로 표시한다', () => {
    const topo: Topo = {
      nodes: [
        { id: 'TC-01', kind: 'device', label: 'TC-01', name: '온도조절기', status: 'DOWN' },
        { id: 'THD-07', kind: 'device', label: 'THD-07', name: '온습도', status: 'OK' },
        { id: 'M2', kind: 'bus', label: 'M2', name: 'RS-485 M2', status: 'DOWN' },
        { id: 'M1', kind: 'bus', label: 'M1', name: 'RS-485 M1', status: 'OK' },
        { id: 'MASTER', kind: 'plc', label: 'MASTER', name: 'Master', status: 'OK' },
        { id: 'EDGE', kind: 'edge', label: 'Edge', name: 'Edge', status: 'OK' },
        { id: 'MES', kind: 'mes', label: 'MES', name: 'MES', status: 'OK' },
      ],
      links: [
        { from: 'TC-01', to: 'M2', status: 'DOWN', comm: 'RS-485' },
        { from: 'THD-07', to: 'M1', status: 'OK', comm: 'RS-485' },
        { from: 'M2', to: 'MASTER', status: 'DOWN', comm: 'RS-485' },
        { from: 'M1', to: 'MASTER', status: 'OK', comm: 'RS-485' },
        { from: 'MASTER', to: 'EDGE', status: 'OK', comm: 'Modbus TCP' },
        { from: 'EDGE', to: 'MES', status: 'OK', comm: 'HTTP' },
      ],
    }
    const { container } = render(
      <MemoryRouter>
        <Topology topo={topo} />
      </MemoryRouter>,
    )
    expect(container.querySelector('[data-node="TC-01"]')).toHaveAttribute('data-status', 'DOWN')
    expect(container.querySelector('[data-node="M1"]')).toHaveAttribute('data-status', 'OK')
    expect(screen.getByRole('link', { name: /TC-01 온도조절기 끊김/ })).toBeInTheDocument()
    expect(container.querySelectorAll('path')).toHaveLength(6)
  })
})
