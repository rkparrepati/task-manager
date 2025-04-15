// LinkAppWizard.test.tsx
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import LinkAppWizard from '../LinkAppWizard'; // adjust the import path
import { AppContext } from 'contexts/AppContext'; // adjust based on your setup
import '@testing-library/jest-dom';

// Mocking the context
const getMockContext = (overrides = {}) => ({
  selectedProducts: [],
  selectedCountries: [],
  currentStep: 0,
  setCurrentStep: jest.fn(),
  ...overrides,
});

describe('LinkAppWizard - Step Navigation & Validation', () => {
  test('should not proceed if no products selected (Step 1)', () => {
    const context = getMockContext({ selectedProducts: [] });

    render(
      <AppContext.Provider value={context}>
        <LinkAppWizard />
      </AppContext.Provider>
    );

    const nextBtn = screen.getByRole('button', { name: /next/i });
    fireEvent.click(nextBtn);

    expect(context.setCurrentStep).not.toHaveBeenCalled();
  });

  test('should proceed if products are selected (Step 1)', () => {
    const context = getMockContext({ selectedProducts: ['product1'] });

    render(
      <AppContext.Provider value={context}>
        <LinkAppWizard />
      </AppContext.Provider>
    );

    const nextBtn = screen.getByRole('button', { name: /next/i });
    fireEvent.click(nextBtn);

    expect(context.setCurrentStep).toHaveBeenCalledWith(1);
  });

  test('should not proceed to Step 3 without countries (Step 2)', () => {
    const context = getMockContext({
      selectedProducts: ['product1'],
      selectedCountries: [],
      currentStep: 1,
    });

    render(
      <AppContext.Provider value={context}>
        <LinkAppWizard />
      </AppContext.Provider>
    );

    const nextBtn = screen.getByRole('button', { name: /next/i });
    fireEvent.click(nextBtn);

    expect(context.setCurrentStep).not.toHaveBeenCalled();
  });

  test('should complete the wizard on final step', () => {
    const onFinish = jest.fn();
    const context = getMockContext({
      selectedProducts: ['product1'],
      selectedCountries: ['US'],
      currentStep: 2,
    });

    render(
      <AppContext.Provider value={context}>
        <LinkAppWizard onFinish={onFinish} />
      </AppContext.Provider>
    );

    const finishBtn = screen.getByRole('button', { name: /finish/i });
    fireEvent.click(finishBtn);

    expect(onFinish).toHaveBeenCalled();
  });
});
