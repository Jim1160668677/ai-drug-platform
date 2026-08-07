import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import GenomeUploader from './GenomeUploader';
import { renderWithProviders } from '@/lib/test-utils';

const mockUploadGenome = vi.fn();
vi.mock('@/lib/api', () => ({
  uploadGenome: (...args: any[]) => mockUploadGenome(...args),
}));

// mock notification 的动态 import
vi.mock('@/lib/notification', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

const VALID_FILE = new File(['content'], 'genome.txt', { type: 'text/plain' });

describe('GenomeUploader 组件', () => {
  beforeEach(() => {
    mockUploadGenome.mockReset();
  });

  describe('初始渲染', () => {
    it('显示上传区域与提示', () => {
      renderWithProviders(<GenomeUploader />);
      expect(
        screen.getByText('点击或拖拽文件到此处上传')
      ).toBeInTheDocument();
      expect(screen.getByText(/23andme/)).toBeInTheDocument();
      expect(screen.getByText(/50MB/)).toBeInTheDocument();
    });

    it('默认基因组版本为 GRCh37', () => {
      renderWithProviders(<GenomeUploader />);
      const select = screen.getByRole('combobox') as HTMLSelectElement;
      expect(select.value).toBe('GRCh37');
    });

    it('defaultGenomeBuild 传入 GRCh38 时生效', () => {
      renderWithProviders(<GenomeUploader defaultGenomeBuild="GRCh38" />);
      const select = screen.getByRole('combobox') as HTMLSelectElement;
      expect(select.value).toBe('GRCh38');
    });

    it('切换基因组版本', () => {
      renderWithProviders(<GenomeUploader />);
      const select = screen.getByRole('combobox') as HTMLSelectElement;
      fireEvent.change(select, { target: { value: 'GRCh38' } });
      expect(select.value).toBe('GRCh38');
    });
  });

  describe('文件选择与验证', () => {
    it('选择有效文件后显示文件信息与上传按钮', () => {
      renderWithProviders(<GenomeUploader />);
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [VALID_FILE] } });
      expect(screen.getByText('genome.txt')).toBeInTheDocument();
      expect(screen.getByText('上传并解析')).toBeInTheDocument();
    });

    it('空文件显示错误', () => {
      renderWithProviders(<GenomeUploader />);
      const emptyFile = new File([], 'empty.txt', { type: 'text/plain' });
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [emptyFile] } });
      expect(screen.getByText('文件为空')).toBeInTheDocument();
      expect(screen.queryByText('上传并解析')).not.toBeInTheDocument();
    });

    it('超过 50MB 的文件显示错误', () => {
      renderWithProviders(<GenomeUploader />);
      const bigFile = new File(
        [new ArrayBuffer(51 * 1024 * 1024)],
        'big.txt',
        { type: 'text/plain' }
      );
      Object.defineProperty(bigFile, 'size', {
        value: 51 * 1024 * 1024,
      });
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [bigFile] } });
      expect(screen.getByText(/超过上限 50MB/)).toBeInTheDocument();
    });

    it('不支持的扩展名显示错误', () => {
      renderWithProviders(<GenomeUploader />);
      const badFile = new File(['x'], 'genome.exe', { type: 'application/octet-stream' });
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [badFile] } });
      expect(screen.getByText(/不支持的文件类型/)).toBeInTheDocument();
      expect(screen.getByText(/\.exe/)).toBeInTheDocument();
    });

    it('支持 .txt/.csv/.tsv/.zip 扩展名', () => {
      renderWithProviders(<GenomeUploader />);
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      const csvFile = new File(['a,b,c'], 'data.csv', { type: 'text/csv' });
      fireEvent.change(input, { target: { files: [csvFile] } });
      expect(screen.getByText('data.csv')).toBeInTheDocument();
      expect(screen.queryByText(/不支持的文件类型/)).not.toBeInTheDocument();
    });

    it('点击移除按钮清除已选文件', () => {
      renderWithProviders(<GenomeUploader />);
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [VALID_FILE] } });
      expect(screen.getByText('genome.txt')).toBeInTheDocument();
      // 移除按钮（X 图标）
      const removeBtn = screen.getAllByRole('button').find((b) =>
        b.querySelector('svg.lucide-x')
      ) as HTMLElement;
      fireEvent.click(removeBtn);
      expect(screen.queryByText('genome.txt')).not.toBeInTheDocument();
    });
  });

  describe('上传流程', () => {
    it('点击上传按钮调用 uploadGenome', async () => {
      mockUploadGenome.mockResolvedValue({
        data: { id: 'g1', file_name: 'genome.txt' },
      });
      const onUploaded = vi.fn();
      renderWithProviders(<GenomeUploader onUploaded={onUploaded} projectId="p1" />);
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [VALID_FILE] } });
      fireEvent.click(screen.getByText('上传并解析'));
      await waitFor(() => {
        expect(mockUploadGenome).toHaveBeenCalledWith(
          VALID_FILE,
          expect.objectContaining({ genomeBuild: 'GRCh37', projectId: 'p1' })
        );
      });
    });

    it('上传成功后触发 onUploaded 回调', async () => {
      const genomeData = { id: 'g1', file_name: 'genome.txt' };
      mockUploadGenome.mockResolvedValue({ data: genomeData });
      const onUploaded = vi.fn();
      renderWithProviders(<GenomeUploader onUploaded={onUploaded} />);
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [VALID_FILE] } });
      fireEvent.click(screen.getByText('上传并解析'));
      await waitFor(() => {
        expect(onUploaded).toHaveBeenCalledWith(genomeData);
      });
    });

    it('上传成功后清空已选文件', async () => {
      mockUploadGenome.mockResolvedValue({ data: { id: 'g1' } });
      renderWithProviders(<GenomeUploader />);
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [VALID_FILE] } });
      expect(screen.getByText('genome.txt')).toBeInTheDocument();
      fireEvent.click(screen.getByText('上传并解析'));
      await waitFor(() => {
        expect(screen.queryByText('genome.txt')).not.toBeInTheDocument();
      });
    });

    it('上传失败显示错误消息', async () => {
      mockUploadGenome.mockRejectedValue({
        response: { data: { detail: '解析失败' } },
      });
      renderWithProviders(<GenomeUploader />);
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [VALID_FILE] } });
      fireEvent.click(screen.getByText('上传并解析'));
      await waitFor(() => {
        expect(screen.getByText('解析失败')).toBeInTheDocument();
      });
      // 文件仍保留以便重试
      expect(screen.getByText('genome.txt')).toBeInTheDocument();
    });

    it('上传失败回退到通用错误消息', async () => {
      // 抛出无 response/detail/message 的错误对象，触发兜底文案
      mockUploadGenome.mockRejectedValue({});
      renderWithProviders(<GenomeUploader />);
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [VALID_FILE] } });
      fireEvent.click(screen.getByText('上传并解析'));
      await waitFor(() => {
        expect(screen.getByText('上传失败，请稍后重试')).toBeInTheDocument();
      });
    });

    it('兼容无 data 包装的响应', async () => {
      const genomeData = { id: 'g1', file_name: 'genome.txt' };
      mockUploadGenome.mockResolvedValue(genomeData);
      const onUploaded = vi.fn();
      renderWithProviders(<GenomeUploader onUploaded={onUploaded} />);
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [VALID_FILE] } });
      fireEvent.click(screen.getByText('上传并解析'));
      await waitFor(() => {
        expect(onUploaded).toHaveBeenCalledWith(genomeData);
      });
    });
  });

  describe('上传中使用当前 genomeBuild', () => {
    it('切换版本后上传使用新版本', async () => {
      mockUploadGenome.mockResolvedValue({ data: { id: 'g1' } });
      renderWithProviders(<GenomeUploader />);
      const select = screen.getByRole('combobox') as HTMLSelectElement;
      fireEvent.change(select, { target: { value: 'GRCh38' } });
      const input = document.querySelector(
        'input[type="file"]'
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { files: [VALID_FILE] } });
      fireEvent.click(screen.getByText('上传并解析'));
      await waitFor(() => {
        expect(mockUploadGenome).toHaveBeenCalledWith(
          VALID_FILE,
          expect.objectContaining({ genomeBuild: 'GRCh38' })
        );
      });
    });
  });
});
