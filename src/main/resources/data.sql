INSERT INTO Task (id, label, category, sub_category, priority, status, status_css, checked, due_date, type)
VALUES
(1, 'Do laundry and fold clothes', 'Personal', 'Daily chores', 'Medium', 'Pending', 'pending', true, 'Today', 'Important'),
(2, 'Create a shopping list for the week', 'Personal', 'Shopping lists', 'Low', 'Approved', 'approved', false, 'Overdue', 'Archive'),
(3, 'Pick up dry cleaning', 'Personal', 'Personal errands', 'High', 'Approved', 'approved', true, 'Upcoming', 'Links'),
(4, 'Practice meditation for 15 minutes', 'Personal', 'Self-care routines', 'Low', 'Pending', 'pending', false, 'Today', 'Important'),
(5, 'Schedule dentist appointment', 'Personal', 'Appointment scheduling', 'High', 'Pending', 'pending', false, 'Upcoming', 'Notes'),
(6, 'Create project timeline and milestones', 'Work', 'Project management', 'High', 'Approved', 'approved', false, 'Upcoming', 'Reminders'),
(7, 'Attend weekly team meeting', 'Work', 'Meetings and appointments', 'Medium', 'Approved', 'approved', false, 'Overdue', 'Important'),
(8, 'Reply to client emails', 'Work', 'Email correspondence', 'High', 'Approved', 'approved', false, 'Upcoming', 'Links'),
(9, 'Conduct market research for new product', 'Work', 'Research and development', 'Medium', 'Pending', 'pending', false, 'Upcoming', 'Notes'),
(10, 'Prepare monthly sales report', 'Work', 'Reporting and documentation', 'High', 'Approved', 'approved', false, 'Today', 'Archive'),
(11, 'Complete math homework assignment', 'Educational', 'Homework assignments', 'Medium', 'Approved', 'approved', false, 'Upcoming', 'Important'),
(12, 'Review notes for upcoming exam', 'Educational', 'Exam preparation', 'High', 'Pending', 'pending', false, 'Today', 'Links'),
(13, 'Research for history research paper', 'Educational', 'Research papers', 'Low', 'Pending', 'pending', false, 'Upcoming', 'Reminders'),
(14, 'Collaborate with classmates on group project', 'Educational', 'Group projects', 'Medium', 'Approved', 'approved', false, 'Today', 'Important'),
(15, 'Enroll in an online coding course', 'Educational', 'Online courses', 'High', 'Approved', 'approved', false, 'Today', 'Notes'),
(16, 'Complete full-body workout routine', 'Health and Fitness', 'Exercise routines', 'High', 'Pending', 'pending', false, 'Upcoming', 'Archive'),
(17, 'Plan healthy meals for the week', 'Health and Fitness', 'Meal planning', 'Medium', 'Approved', 'approved', false, 'Overdue', 'Important'),
(18, 'Schedule annual physical exam', 'Health and Fitness', 'Doctor appointments', 'High', 'Approved', 'approved', false, 'Today', 'Links'),
(19, 'Organize medication schedule', 'Health and Fitness', 'Medication management', 'Low', 'Pending', 'pending', false, 'Today', 'Reminders'),
(20, 'Track daily water intake', 'Health and Fitness', 'Health tracking', 'Low', 'Approved', 'approved', false, 'Upcoming', 'Notes'),
(21, 'Create monthly budget spreadsheet', 'Financial', 'Budgeting', 'Medium', 'Approved', 'approved', false, 'Upcoming', 'Important'),
(22, 'Pay utility bills', 'Financial', 'Bill payments', 'High', 'Pending', 'pending', false, 'Today', 'Links'),
(23, 'Review investment portfolio', 'Financial', 'Investment management', 'High', 'Approved', 'approved', false, 'Upcoming', 'Reminders'),
(24, 'Gather tax documents for filing', 'Financial', 'Tax filing', 'Medium', 'Approved', 'approved', false, 'Today', 'Archive'),
(25, 'Track daily expenses in finance app', 'Financial', 'Expense tracking', 'Low', 'Approved', 'approved', false, 'Upcoming', 'Important'),
(26, 'Plan company team-building event', 'Social', 'Event planning', 'High', 'Waiting', 'waiting', false, 'Upcoming', 'Links'),
(27, 'Attend friends birthday party', 'Social', 'Social gatherings', 'Low', 'Pending', 'pending', false, 'Today', 'Reminders'),
(28, 'Attend industry networking event', 'Social', 'Networking', 'Medium', 'Completed', 'completed', false, 'Overdue', 'Important'),
(29, 'Call parents to catch up', 'Social', 'Keeping in touch with friends and family', 'Low', 'Pending', 'pending', false, 'Today', 'Links'),
(30, 'Volunteer at local food bank', 'Social', 'Volunteer work', 'High', 'In Progress', 'in-progress', false, 'Today', 'Notes'),
(31, 'Book flights for vacation', 'Travel', 'Booking flights and accommodations', 'High', 'Pending', 'pending', false, 'Upcoming', 'Important'),
(32, 'Create itinerary for trip', 'Travel', 'Itinerary planning', 'Medium', 'Approved', 'approved', false, 'Today', 'Links'),
(33, 'Make packing list for vacation', 'Travel', 'Packing lists', 'Low', 'Waiting', 'waiting', false, 'Upcoming', 'Reminders'),
(34, 'Research tourist attractions at destination', 'Travel', 'Researching destinations', 'Medium', 'In Review', 'in-review', false, 'Today', 'Archive'),
(35, 'Arrange transportation to airport', 'Travel', 'Transportation arrangements', 'High', 'Completed', 'completed', false, 'Overdue', 'Important'),
(36, 'Clean kitchen and wash dishes', 'Household', 'Cleaning schedules', 'Medium', 'In Progress', 'in-progress', false, 'Today', 'Links'),
(37, 'Fix leaking faucet in bathroom', 'Household', 'Maintenance and repairs', 'High', 'Approved', 'approved', false, 'Today', 'Reminders'),
(38, 'Go grocery shopping', 'Household', 'Grocery shopping', 'Low', 'In Review', 'in-review', false, 'Today', 'Important'),
(39, 'Paint bedroom walls', 'Household', 'Home improvement projects', 'High', 'Completed', 'completed', false, 'Overdue', 'Links'),
(40, 'Feed and groom the pet', 'Household', 'Pet care', 'Low', 'Pending', 'pending', false, 'Today', 'Reminders'),
(41, 'Take online course to learn new programming language', 'Career Development', 'Skill development', 'High', 'In Review', 'in-review', false, 'Today', 'Important'),
(42, 'Attend industry conference on professional development', 'Career Development', 'Networking events', 'Medium', 'In Progress', 'in-progress', false, 'Today', 'Links'),
(43, 'Update resume and LinkedIn profile', 'Career Development', 'Job searching', 'High', 'Approved', 'approved', false, 'Upcoming', 'Reminders'),
(44, 'Apply for three job positions', 'Career Development', 'Resume/CV updating', 'High', 'Waiting', 'waiting', false, 'Today', 'Important'),
(45, 'Study for professional certification exam', 'Career Development', 'Professional certification', 'Medium', 'In Progress', 'in-progress', false, 'Today', 'Notes'),
(46, 'Create 5-year career plan', 'Goal-oriented', 'Long-term planning', 'High', 'In Review', 'in-review', false, 'Today', 'Important'),
(47, 'Track progress towards fitness goals', 'Goal-oriented', 'Milestone tracking', 'Medium', 'Completed', 'completed', false, 'Overdue', 'Links'),
(48, 'Set aside time each week for personal growth', 'Goal-oriented', 'Goal setting', 'Low', 'Pending', 'pending', false, 'Today', 'Reminders'),
(49, 'Create vision board for future aspirations', 'Goal-oriented', 'Progress monitoring', 'Low', 'Approved', 'approved', false, 'Today', 'Important'),
(50, 'Implement daily reward system for achieving goals', 'Goal-oriented', 'Reward systems', 'Medium', 'In Progress', 'in-progress', false, 'Today', 'Notes');


INSERT INTO task_category (name, css_class, img, label) VALUES ('Personal', 'feather feather-users', 'usersImg', 'Personal');
INSERT INTO task_category (name, css_class, img, label) VALUES ('Work', 'feather feather-sun', 'sunImg', 'Work');
INSERT INTO task_category (name, css_class, img, label) VALUES ('Educational', 'feather feather-trending-up', 'trendingImg', 'Educational');
INSERT INTO task_category (name, css_class, img, label) VALUES ('Health and Fitness', 'feather feather-zap', 'zapImg', 'Health and Fitness');
INSERT INTO task_category (name, css_class, img, label) VALUES ('Financial', 'feather feather-zap', 'zapImg', 'Financial');
INSERT INTO task_category (name, css_class, img, label) VALUES ('Social', 'feather feather-zap', 'zapImg', 'Social');
INSERT INTO task_category (name, css_class, img, label) VALUES ('Travel', 'feather feather-zap', 'zapImg', 'Travel');
INSERT INTO task_category (name, css_class, img, label) VALUES ('Household', 'feather feather-zap', 'zapImg', 'Household');
INSERT INTO task_category (name, css_class, img, label) VALUES ('Career Development', 'feather feather-zap', 'zapImg', 'Career Development');
INSERT INTO task_category (name, css_class, img, label) VALUES ('Goal-oriented', 'feather feather-zap', 'zapImg', 'Goal-oriented');
