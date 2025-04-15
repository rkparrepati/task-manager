const mockContext = {
  selectedRow: [], // No products selected
  setIsAdded: jest.fn(),
  applicationIdentifier: {},
  setApplicationIdentifier: jest.fn(),
  setIsEdited: jest.fn(),
  activeRows: [],
  setChecked: jest.fn(),
  error: false,
};

it("blocks next step when no product is selected", async () => {
  render(
    <RowContext.Provider value={mockContext}>
      <AddApplicationsGrid />
    </RowContext.Provider>
  );
  
  const nextButton = screen.getByRole("button", { name: /next/i });
  expect(nextButton).toBeDisabled(); // This should now always pass
});
