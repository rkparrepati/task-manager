// Add this test case after the existing test cases in the describe block
test("handleCancelConfirm navigates or calls handleNext based on byPassAddDupRecord", async () => {
  const mockNavigate = jest.fn();
  jest.mock("react-router-dom", () => ({
    ...jest.requireActual("react-router-dom"),
    useNavigate: () => mockNavigate,
  }));

  const contextValue = {
    ...mockRowContextValues,
    byPassAddDupRecord: true, // Test when byPassAddDupRecord is true
  };

  await act(async () => {
    render(
      <Router>
        <RowContext.Provider value={contextValue}>
          <AddApplicationsGrid />
        </RowContext.Provider>
      </Router>
    );
  });

  fireEvent.click(screen.getByText("Yes")); // Simulate confirming cancel action

  await waitFor(() => {
    expect(mockNavigate).not.toHaveBeenCalled(); // handleNext should be called instead
  });

  // Test when byPassAddDupRecord is false
  contextValue.byPassAddDupRecord = false;

  await act(async () => {
    render(
      <Router>
        <RowContext.Provider value={contextValue}>
          <AddApplicationsGrid />
        </RowContext.Provider>
      </Router>
    );
  });

  fireEvent.click(screen.getByText("Yes")); // Simulate confirming cancel action

  await waitFor(() => {
    expect(mockNavigate).toHaveBeenCalledWith("/applicationdetails"); // Should navigate to application details
  });
});
